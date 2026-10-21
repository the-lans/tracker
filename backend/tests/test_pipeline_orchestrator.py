import asyncio
import uuid
from pathlib import Path

import pytest
import sqlalchemy as sa
from claude_agent_sdk import (
    AssistantMessage,
    CLIConnectionError,
    CLINotFoundError,
    Message,
    ProcessError,
    TextBlock,
)
from claude_agent_sdk.types import AssistantMessageError
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from clients.claude_agent import ClaudeCodeSession
from db.models.enums import (
    EnvVariableScope,
    NodeLogStatus,
    NodeType,
    ScriptLanguage,
    TaskStatus,
    UserRole,
)
from db.models.env_vars import EnvVariable, TaskEnvVariable
from db.models.logs import NodeLog
from db.models.pipelines import Node, Pipeline, TaskNode
from db.models.tasks import Task
from db.models.users import User
from services.crypto import encrypt
from services.pipeline_orchestrator import (
    CheckpointDecision,
    StopGuard,
    compute_retry_delay_seconds,
    run_pipeline,
)
from services.plan_mode import ActiveNodeContext
from services.task_control import TaskControlCommand, request_task_control
from tests.fakes import FakeClaudeAgentClient, make_assistant_error, make_result_message

_GENEROUS_TIMEOUT_SECONDS = 30


async def _make_task_with_pipeline(db_session: AsyncSession) -> Task:
    user = User(email=f"{uuid.uuid4()}@example.com", role=UserRole.USER)
    db_session.add(user)
    await db_session.flush()
    pipeline = Pipeline(name="p", is_archived=False, created_by=user.id)
    db_session.add(pipeline)
    await db_session.flush()
    task = Task(
        code=f"RR-{uuid.uuid4().hex[:5]}",
        title="t",
        description="d",
        created_by=user.id,
        pipeline_id=pipeline.id,
        status=TaskStatus.IN_PROGRESS,
    )
    db_session.add(task)
    await db_session.flush()
    return task


async def _add_node(
    db_session: AsyncSession,
    task: Task,
    *,
    order_index: int,
    is_enabled: bool = True,
    **node_kwargs: object,
) -> Node:
    defaults: dict[str, object] = {
        "pipeline_id": task.pipeline_id,
        "order_index": order_index,
        "name": f"node-{order_index}",
        "timeout_seconds": _GENEROUS_TIMEOUT_SECONDS,
        "max_retries": 3,
        "retry_base_delay_seconds": 0,
        "is_skipped": False,
        "is_library_item": False,
        "is_archived": False,
        "created_by": task.created_by,
    }
    defaults.update(node_kwargs)
    node = Node(**defaults)
    db_session.add(node)
    await db_session.flush()
    db_session.add(
        TaskNode(task_id=task.id, node_id=node.id, order_index=order_index, is_enabled=is_enabled),
    )
    await db_session.flush()
    return node


async def _node_logs_for(db_session: AsyncSession, task_id: uuid.UUID) -> list[NodeLog]:
    stmt = (
        sa.select(NodeLog)
        .where(NodeLog.task_id == task_id)
        .order_by(NodeLog.started_at, NodeLog.id)
    )
    return list((await db_session.execute(stmt)).scalars().all())


def test_compute_retry_delay_seconds_grows_exponentially() -> None:
    assert compute_retry_delay_seconds(1, 5) == 5.0
    assert compute_retry_delay_seconds(2, 5) == 10.0
    assert compute_retry_delay_seconds(3, 5) == 20.0


async def test_run_pipeline_executes_nodes_in_order_and_threads_output(
    db_session: AsyncSession,
    tmp_path: Path,
) -> None:
    task = await _make_task_with_pipeline(db_session)
    await _add_node(
        db_session,
        task,
        order_index=0,
        node_type=NodeType.PLAIN_PROMPT,
        prompt_template="первый шаг",
    )
    await _add_node(
        db_session,
        task,
        order_index=1,
        node_type=NodeType.PLAIN_PROMPT,
        prompt_template="используем: {{node.llm_output}}",
    )
    # Первый узел должен вернуть непустой текст, чтобы второй мог на него сослаться.
    fake = FakeClaudeAgentClient(
        messages_per_query=[
            [
                AssistantMessage(
                    content=[TextBlock(text="результат первого шага")],
                    model="claude",
                ),
                make_result_message(),
            ],
            [make_result_message()],
        ],
    )
    session = ClaudeCodeSession(fake)

    outcome = await run_pipeline(db_session, task=task, claude_session=session, repos_path=tmp_path)

    assert outcome.completed is True
    logs = await _node_logs_for(db_session, task.id)
    assert len(logs) == 2
    assert logs[0].status is NodeLogStatus.SUCCESS
    assert logs[1].rendered_prompt == "используем: результат первого шага"


async def test_run_pipeline_skips_disabled_nodes_without_node_log(
    db_session: AsyncSession,
    tmp_path: Path,
) -> None:
    task = await _make_task_with_pipeline(db_session)
    await _add_node(
        db_session,
        task,
        order_index=0,
        node_type=NodeType.PLAIN_PROMPT,
        prompt_template="шаг 1",
    )
    disabled_node = await _add_node(
        db_session,
        task,
        order_index=1,
        is_enabled=False,
        node_type=NodeType.PLAIN_PROMPT,
        prompt_template="шаг 2 (отключён)",
    )
    await _add_node(
        db_session,
        task,
        order_index=2,
        node_type=NodeType.PLAIN_PROMPT,
        prompt_template="шаг 3",
    )
    fake = FakeClaudeAgentClient(
        messages_per_query=[[make_result_message()], [make_result_message()]],
    )
    session = ClaudeCodeSession(fake)

    outcome = await run_pipeline(db_session, task=task, claude_session=session, repos_path=tmp_path)

    assert outcome.completed is True
    logs = await _node_logs_for(db_session, task.id)
    assert len(logs) == 2
    assert all(log.node_id != disabled_node.id for log in logs)


async def test_run_pipeline_retries_and_fails_after_exhausting_attempts(
    db_session: AsyncSession,
    tmp_path: Path,
) -> None:
    task = await _make_task_with_pipeline(db_session)
    await _add_node(
        db_session,
        task,
        order_index=0,
        node_type=NodeType.PLAIN_PROMPT,
        prompt_template="ненадёжный шаг",
        max_retries=2,
        retry_base_delay_seconds=0,
    )
    await _add_node(
        db_session,
        task,
        order_index=1,
        node_type=NodeType.PLAIN_PROMPT,
        prompt_template="никогда не выполнится",
    )
    fake = FakeClaudeAgentClient(
        messages_per_query=[
            [make_result_message(is_error=True)],
            [make_result_message(is_error=True)],
        ],
    )
    session = ClaudeCodeSession(fake)

    outcome = await run_pipeline(db_session, task=task, claude_session=session, repos_path=tmp_path)

    assert outcome.completed is False
    assert outcome.failed_order_index == 0
    logs = await _node_logs_for(db_session, task.id)
    assert len(logs) == 2
    assert [log.attempt_number for log in logs] == [1, 2]
    assert all(log.status is NodeLogStatus.FAILED for log in logs)
    assert len(fake.queries) == 2


async def test_run_pipeline_stops_at_clear_context_and_reports_order_index(
    db_session: AsyncSession,
    tmp_path: Path,
) -> None:
    task = await _make_task_with_pipeline(db_session)
    await _add_node(
        db_session,
        task,
        order_index=0,
        node_type=NodeType.PLAIN_PROMPT,
        prompt_template="шаг 1",
    )
    await _add_node(db_session, task, order_index=1, node_type=NodeType.CLEAR_CONTEXT)
    await _add_node(
        db_session,
        task,
        order_index=2,
        node_type=NodeType.PLAIN_PROMPT,
        prompt_template="после очистки",
    )
    task.session_id = "sess-to-be-cleared"
    fake = FakeClaudeAgentClient(messages_per_query=[[make_result_message()]])
    session = ClaudeCodeSession(fake)

    outcome = await run_pipeline(db_session, task=task, claude_session=session, repos_path=tmp_path)

    assert outcome.completed is False
    assert outcome.context_cleared_at_order_index == 1
    assert fake.disconnected is True
    assert task.session_id is None
    logs = await _node_logs_for(db_session, task.id)
    # Первый шаг и сама clear_context (успешная запись нужна инварианту done);
    # шаг после очистки не выполнялся — пайплайн остановился.
    assert len(logs) == 2
    assert {log.status for log in logs} == {NodeLogStatus.SUCCESS}
    assert all(log.rendered_prompt != "после очистки" for log in logs)


async def test_run_pipeline_start_after_order_index_skips_earlier_nodes(
    db_session: AsyncSession,
    tmp_path: Path,
) -> None:
    task = await _make_task_with_pipeline(db_session)
    await _add_node(
        db_session,
        task,
        order_index=0,
        node_type=NodeType.PLAIN_PROMPT,
        prompt_template="уже выполнено",
    )
    await _add_node(
        db_session,
        task,
        order_index=1,
        node_type=NodeType.PLAIN_PROMPT,
        prompt_template="продолжение",
    )
    fake = FakeClaudeAgentClient(messages_per_query=[[make_result_message()]])
    session = ClaudeCodeSession(fake)

    outcome = await run_pipeline(
        db_session,
        task=task,
        claude_session=session,
        repos_path=tmp_path,
        start_after_order_index=0,
    )

    assert outcome.completed is True
    logs = await _node_logs_for(db_session, task.id)
    assert len(logs) == 1
    assert logs[0].rendered_prompt == "продолжение"


async def test_run_pipeline_executes_script_node_in_docker(
    db_session: AsyncSession,
    tmp_path: Path,
) -> None:
    task = await _make_task_with_pipeline(db_session)
    await _add_node(
        db_session,
        task,
        order_index=0,
        node_type=NodeType.SCRIPT,
        script_language=ScriptLanguage.PYTHON,
        script_content="print('из оркестратора')",
    )
    session = ClaudeCodeSession(FakeClaudeAgentClient(messages_per_query=[]))

    outcome = await run_pipeline(db_session, task=task, claude_session=session, repos_path=tmp_path)

    assert outcome.completed is True
    logs = await _node_logs_for(db_session, task.id)
    assert logs[0].script_exit_code == 0
    assert "из оркестратора" in (logs[0].script_stdout or "")


class TestScriptEnv:
    """Раздел 11.4: переменные задачи — в контейнер, системный токен GitLab — нет."""

    async def test_without_gitlab_token(
        self,
        db_session: AsyncSession,
        tmp_path: Path,
    ) -> None:
        task = await _make_task_with_pipeline(db_session)
        db_session.add_all(
            [
                TaskEnvVariable(
                    task_id=task.id,
                    key="API_URL",
                    value_encrypted=encrypt("из задачи"),
                ),
                EnvVariable(
                    key="GITLAB_TOKEN",
                    value_encrypted=encrypt("секрет"),
                    scope=EnvVariableScope.GLOBAL,
                ),
            ],
        )
        await _add_node(
            db_session,
            task,
            order_index=0,
            node_type=NodeType.SCRIPT,
            script_language=ScriptLanguage.PYTHON,
            script_content=(
                "import os\nprint(os.environ['API_URL'], os.environ.get('GITLAB_TOKEN'))"
            ),
        )
        session = ClaudeCodeSession(FakeClaudeAgentClient(messages_per_query=[]))

        outcome = await run_pipeline(
            db_session,
            task=task,
            claude_session=session,
            repos_path=tmp_path,
        )

        assert outcome.completed is True
        logs = await _node_logs_for(db_session, task.id)
        assert (logs[0].script_stdout or "").strip() == "из задачи None"


async def test_run_pipeline_executes_plan_prompt_node_with_active_node_context(
    db_session: AsyncSession,
    tmp_path: Path,
) -> None:
    task = await _make_task_with_pipeline(db_session)
    await _add_node(
        db_session,
        task,
        order_index=0,
        node_type=NodeType.PLAN_PROMPT,
        prompt_template="составь план для {{task.code}}",
    )
    await _add_node(
        db_session,
        task,
        order_index=1,
        node_type=NodeType.PLAIN_PROMPT,
        prompt_template="используем план: {{node.plan_text}}",
    )

    node_logs_snapshot: list[NodeLog] = []

    async def _accept_plan_for_current_node() -> None:
        # Симулирует callback разрешений SDK (раздел 9.6): к моменту вызова
        # query() оркестратор уже выставил context.node_log_id на ноду
        # plan_prompt (см. active_node_context ниже).
        node_log = await db_session.get(NodeLog, context.node_log_id)
        assert node_log is not None
        node_log.pending_plan_text = "1. Шаг раз\n2. Шаг два"
        node_log.status = NodeLogStatus.SUCCESS
        await db_session.commit()
        node_logs_snapshot.append(node_log)

    context = ActiveNodeContext()
    fake = FakeClaudeAgentClient(
        messages_per_query=[[make_result_message()], [make_result_message()]],
        on_query=_accept_plan_for_current_node,
    )
    session = ClaudeCodeSession(fake)

    outcome = await run_pipeline(
        db_session,
        task=task,
        claude_session=session,
        repos_path=tmp_path,
        active_node_context=context,
    )

    assert outcome.completed is True
    assert fake.permission_modes == ["plan"]
    logs = await _node_logs_for(db_session, task.id)
    assert logs[0].status is NodeLogStatus.SUCCESS
    assert logs[1].rendered_prompt == "используем план: 1. Шаг раз\n2. Шаг два"


async def test_run_pipeline_saves_session_id_after_first_turn(
    db_session: AsyncSession,
    tmp_path: Path,
) -> None:
    task = await _make_task_with_pipeline(db_session)
    await _add_node(
        db_session,
        task,
        order_index=0,
        node_type=NodeType.PLAIN_PROMPT,
        prompt_template="шаг",
    )
    assert task.session_id is None
    fake = FakeClaudeAgentClient(
        messages_per_query=[[make_result_message(session_id="sess-new")]],
    )

    await run_pipeline(
        db_session,
        task=task,
        claude_session=ClaudeCodeSession(fake),
        repos_path=tmp_path,
    )

    # Раздел 6.1: без сохранённого session_id перезапуск не смог бы продолжить сессию.
    await db_session.refresh(task)
    assert task.session_id == "sess-new"


async def test_checkpoint_runs_before_each_enabled_node_and_can_stop(
    db_session: AsyncSession,
    tmp_path: Path,
) -> None:
    task = await _make_task_with_pipeline(db_session)
    await _add_node(
        db_session, task, order_index=0, node_type=NodeType.PLAIN_PROMPT, prompt_template="шаг 0"
    )
    await _add_node(
        db_session,
        task,
        order_index=1,
        node_type=NodeType.PLAIN_PROMPT,
        prompt_template="отключён",
        is_enabled=False,
    )
    await _add_node(
        db_session, task, order_index=2, node_type=NodeType.PLAIN_PROMPT, prompt_template="шаг 2"
    )
    fake = FakeClaudeAgentClient(messages_per_query=[[make_result_message()]])
    seen: list[int] = []

    async def checkpoint(order_index: int) -> CheckpointDecision:
        seen.append(order_index)
        return CheckpointDecision.STOP if order_index == 2 else CheckpointDecision.CONTINUE

    outcome = await run_pipeline(
        db_session,
        task=task,
        claude_session=ClaudeCodeSession(fake),
        repos_path=tmp_path,
        checkpoint=checkpoint,
    )

    assert seen == [0, 2]
    assert fake.queries == ["шаг 0"]
    assert outcome.stopped is True
    assert outcome.completed is False
    assert outcome.failed_order_index == 2


async def test_stop_during_node_marks_it_stopped_without_retry(
    db_session: AsyncSession,
    redis_client: Redis,
    tmp_path: Path,
) -> None:
    task = await _make_task_with_pipeline(db_session)
    await _add_node(
        db_session,
        task,
        order_index=0,
        node_type=NodeType.PLAIN_PROMPT,
        prompt_template="долгий шаг",
        max_retries=3,
    )
    await _add_node(
        db_session,
        task,
        order_index=1,
        node_type=NodeType.PLAIN_PROMPT,
        prompt_template="не дойдёт",
    )
    fake = FakeClaudeAgentClient(messages_per_query=[[make_result_message()]])
    fake.message_delay_seconds = 30

    async def press_stop() -> None:
        await asyncio.sleep(0.3)
        await request_task_control(redis_client, task.id, TaskControlCommand.STOP)
        # Хвост прерванного хода CLI присылает сразу после interrupt().
        fake.message_delay_seconds = 0

    presser = asyncio.ensure_future(press_stop())
    outcome = await asyncio.wait_for(
        run_pipeline(
            db_session,
            task=task,
            claude_session=ClaudeCodeSession(fake),
            repos_path=tmp_path,
            stop_guard=StopGuard(redis_client=redis_client, task_id=task.id),
        ),
        timeout=10,
    )
    await presser

    assert outcome.stopped is True
    assert outcome.failed_order_index == 0
    assert fake.queries == ["долгий шаг"]
    assert fake.interrupted is True
    logs = await _node_logs_for(db_session, task.id)
    assert [log.status for log in logs] == [NodeLogStatus.STOPPED]


class TestFailureKinds:
    """Раздел 17.3: временный сбой повторяется, постоянный — нет."""

    async def _task_with_node(self, db_session: AsyncSession, *, max_retries: int = 3) -> Task:
        task = await _make_task_with_pipeline(db_session)
        await _add_node(
            db_session,
            task,
            order_index=0,
            node_type=NodeType.PLAIN_PROMPT,
            prompt_template="шаг",
            max_retries=max_retries,
            retry_base_delay_seconds=0,
        )
        return task

    @pytest.mark.parametrize(
        ("assistant_error", "expected_attempts"),
        [
            ("authentication_failed", 1),
            ("billing_error", 1),
            ("rate_limit", 3),
            ("server_error", 3),
        ],
    )
    async def test_assistant_error(
        self,
        db_session: AsyncSession,
        tmp_path: Path,
        assistant_error: AssistantMessageError,
        expected_attempts: int,
    ) -> None:
        task = await self._task_with_node(db_session)
        failing_turn: list[Message] = [
            make_assistant_error(assistant_error),
            make_result_message(is_error=True),
        ]
        fake = FakeClaudeAgentClient(messages_per_query=[failing_turn] * 3)

        outcome = await run_pipeline(
            db_session,
            task=task,
            claude_session=ClaudeCodeSession(fake),
            repos_path=tmp_path,
        )

        assert outcome.completed is False
        assert len(fake.queries) == expected_attempts
        logs = await _node_logs_for(db_session, task.id)
        assert [log.status for log in logs] == [NodeLogStatus.FAILED] * expected_attempts

    async def test_crash_recovered(
        self,
        db_session: AsyncSession,
        tmp_path: Path,
    ) -> None:
        task = await self._task_with_node(db_session)
        crashed = FakeClaudeAgentClient(
            messages_per_query=[],
            failures_per_query={0: ProcessError("CLI упал", exit_code=1)},
        )
        replacement = FakeClaudeAgentClient(messages_per_query=[[make_result_message()]])
        session = ClaudeCodeSession(crashed)
        recoveries: list[str] = []

        async def recover() -> None:
            recoveries.append("recovered")
            await session.replace_client(replacement)

        outcome = await run_pipeline(
            db_session,
            task=task,
            claude_session=session,
            repos_path=tmp_path,
            recover_session=recover,
        )

        assert outcome.completed is True
        assert recoveries == ["recovered"]
        assert replacement.connected is True
        logs = await _node_logs_for(db_session, task.id)
        assert [log.status for log in logs] == [NodeLogStatus.FAILED, NodeLogStatus.SUCCESS]

    async def test_missing_cli_is_not_retried(
        self,
        db_session: AsyncSession,
        tmp_path: Path,
    ) -> None:
        task = await self._task_with_node(db_session)
        fake = FakeClaudeAgentClient(
            messages_per_query=[],
            failures_per_query={0: CLINotFoundError("claude не найден")},
        )

        async def recover() -> None:
            pytest.fail("постоянный сбой не должен переподключать сессию")

        outcome = await run_pipeline(
            db_session,
            task=task,
            claude_session=ClaudeCodeSession(fake),
            repos_path=tmp_path,
            recover_session=recover,
        )

        assert outcome.completed is False
        assert len(fake.queries) == 1

    async def test_crash_without_recovery_fails_node(
        self,
        db_session: AsyncSession,
        tmp_path: Path,
    ) -> None:
        task = await self._task_with_node(db_session)
        fake = FakeClaudeAgentClient(
            messages_per_query=[],
            failures_per_query={0: ProcessError("CLI упал", exit_code=1)},
        )

        outcome = await run_pipeline(
            db_session,
            task=task,
            claude_session=ClaudeCodeSession(fake),
            repos_path=tmp_path,
        )

        assert outcome.completed is False
        assert len(fake.queries) == 1

    async def test_failed_recovery_propagates(
        self,
        db_session: AsyncSession,
        tmp_path: Path,
    ) -> None:
        task = await self._task_with_node(db_session)
        fake = FakeClaudeAgentClient(
            messages_per_query=[],
            failures_per_query={0: ProcessError("CLI упал", exit_code=1)},
        )

        async def recover() -> None:
            message = "не удалось поднять процесс"
            raise CLIConnectionError(message)

        with pytest.raises(CLIConnectionError):
            await run_pipeline(
                db_session,
                task=task,
                claude_session=ClaudeCodeSession(fake),
                repos_path=tmp_path,
                recover_session=recover,
            )
