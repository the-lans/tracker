import uuid
from pathlib import Path

import pytest
from claude_agent_sdk import AssistantMessage, TextBlock
from sqlalchemy.ext.asyncio import AsyncSession

from clients.claude_agent import ClaudeCodeSession
from db.models.enums import (
    NodeLogStatus,
    NodeLogTriggerType,
    NodeType,
    PermissionMode,
    ScriptLanguage,
    TaskStatus,
    UserRole,
)
from db.models.logs import NodeLog
from db.models.pipelines import Node
from db.models.tasks import Task
from db.models.users import User
from services.nodes import dispatch
from services.nodes.dispatch import (
    NodeExecutionOutcome,
    execute_llm_node,
    execute_llm_node_with_timeout,
    execute_node,
    execute_plan_prompt_node,
    execute_script_node,
    record_sdk_failure,
    resolve_node_prompt,
)
from services.nodes.script import ScriptExecutionResult
from tests.factories import make_pipeline, make_task, make_user
from tests.fakes import FakeClaudeAgentClient, make_result_message

_GENEROUS_TIMEOUT_SECONDS = 30


async def _make_task(db_session: AsyncSession) -> Task:
    user = await make_user(db_session)
    pipeline = await make_pipeline(db_session, created_by=user.id)
    return await make_task(
        db_session,
        created_by=user.id,
        pipeline_id=pipeline.id,
        status=TaskStatus.IN_PROGRESS,
    )


async def test_resolve_node_prompt_renders_plain_prompt_template(db_session: AsyncSession) -> None:
    task = await _make_task(db_session)
    node = Node(
        created_by=task.created_by,
        pipeline_id=task.pipeline_id,
        order_index=0,
        name="n",
        node_type=NodeType.PLAIN_PROMPT,
        prompt_template="Задача {{task.code}}",
        is_library_item=False,
        is_archived=False,
    )
    db_session.add(node)
    await db_session.flush()

    prompt = await resolve_node_prompt(db_session, node=node, task=task)

    assert prompt.text == f"Задача {task.code}"


async def test_resolve_node_prompt_returns_slash_command_literally_unmodified(
    db_session: AsyncSession,
) -> None:
    task = await _make_task(db_session)
    literal_invocation = "/review {{task.code}} $ARGUMENTS"
    node = Node(
        created_by=task.created_by,
        pipeline_id=task.pipeline_id,
        order_index=0,
        name="n",
        node_type=NodeType.SLASH_COMMAND,
        command_invocation=literal_invocation,
        is_library_item=False,
        is_archived=False,
    )
    db_session.add(node)
    await db_session.flush()

    prompt = await resolve_node_prompt(db_session, node=node, task=task)

    # Раздел 4: слэш-команда никогда не проходит через шаблонизатор — если
    # бы прошла, "{{task.code}}" был бы заменён на реальный код задачи.
    assert prompt.text == prompt.display == literal_invocation


async def test_resolve_node_prompt_raises_when_slash_command_missing_invocation(
    db_session: AsyncSession,
) -> None:
    task = await _make_task(db_session)
    node = Node(
        created_by=task.created_by,
        pipeline_id=task.pipeline_id,
        order_index=0,
        name="n",
        node_type=NodeType.SLASH_COMMAND,
        is_library_item=False,
        is_archived=False,
    )
    db_session.add(node)
    await db_session.flush()

    with pytest.raises(ValueError, match="command_invocation"):
        await resolve_node_prompt(db_session, node=node, task=task)


async def test_resolve_node_prompt_raises_when_plain_prompt_missing_template(
    db_session: AsyncSession,
) -> None:
    task = await _make_task(db_session)
    node = Node(
        created_by=task.created_by,
        pipeline_id=task.pipeline_id,
        order_index=0,
        name="n",
        node_type=NodeType.PLAIN_PROMPT,
        is_library_item=False,
        is_archived=False,
    )
    db_session.add(node)
    await db_session.flush()

    with pytest.raises(ValueError, match="prompt_template"):
        await resolve_node_prompt(db_session, node=node, task=task)


async def test_execute_llm_node_returns_success_outcome() -> None:
    fake = FakeClaudeAgentClient(messages_per_query=[[make_result_message()]])
    session = ClaudeCodeSession(fake)

    outcome = await execute_llm_node(session, "hi")

    assert outcome.success is True
    assert outcome.llm_output_text == ""


async def test_execute_llm_node_returns_failure_outcome_on_error_result() -> None:
    fake = FakeClaudeAgentClient(messages_per_query=[[make_result_message(is_error=True)]])
    session = ClaudeCodeSession(fake)

    outcome = await execute_llm_node(session, "hi")

    assert outcome.success is False
    assert outcome.error_message is not None


async def test_execute_llm_node_with_timeout_succeeds_within_budget() -> None:
    fake = FakeClaudeAgentClient(messages_per_query=[[make_result_message()]])
    session = ClaudeCodeSession(fake)

    outcome = await execute_llm_node_with_timeout(
        session,
        "hi",
        timeout_seconds=_GENEROUS_TIMEOUT_SECONDS,
    )

    assert outcome.success is True


async def test_execute_llm_node_with_timeout_interrupts_and_fails_on_timeout() -> None:
    fake = FakeClaudeAgentClient(messages_per_query=[[make_result_message()]])
    session = ClaudeCodeSession(fake)

    outcome = await execute_llm_node_with_timeout(session, "hi", timeout_seconds=0.001)

    assert outcome.success is False
    assert outcome.error_message == "Превышен таймаут выполнения"
    assert fake.interrupted is True


async def test_execute_script_node_returns_success_outcome(tmp_path: Path) -> None:
    node = Node(
        created_by=uuid.uuid4(),
        name="n",
        node_type=NodeType.SCRIPT,
        script_language=ScriptLanguage.PYTHON,
        script_content="print('ok')",
        timeout_seconds=_GENEROUS_TIMEOUT_SECONDS,
        is_library_item=True,
        is_archived=False,
    )

    outcome = await execute_script_node(node, repos_path=tmp_path)

    assert outcome.success is True
    assert outcome.script_exit_code == 0
    assert "ok" in (outcome.script_stdout or "")


async def test_execute_script_node_returns_failure_outcome_on_nonzero_exit(tmp_path: Path) -> None:
    node = Node(
        created_by=uuid.uuid4(),
        name="n",
        node_type=NodeType.SCRIPT,
        script_language=ScriptLanguage.PYTHON,
        script_content="import sys; sys.exit(3)",
        timeout_seconds=_GENEROUS_TIMEOUT_SECONDS,
        is_library_item=True,
        is_archived=False,
    )

    outcome = await execute_script_node(node, repos_path=tmp_path)

    assert outcome.success is False
    assert outcome.script_exit_code == 3


async def test_execute_script_node_raises_when_missing_content(tmp_path: Path) -> None:
    node = Node(
        created_by=uuid.uuid4(),
        name="n",
        node_type=NodeType.SCRIPT,
        timeout_seconds=_GENEROUS_TIMEOUT_SECONDS,
        is_library_item=True,
        is_archived=False,
    )

    with pytest.raises(ValueError, match="script_content"):
        await execute_script_node(node, repos_path=tmp_path)


async def test_execute_node_dispatches_script_type_to_docker(tmp_path: Path) -> None:
    node = Node(
        created_by=uuid.uuid4(),
        name="n",
        node_type=NodeType.SCRIPT,
        script_language=ScriptLanguage.PYTHON,
        script_content="print('через execute_node')",
        timeout_seconds=_GENEROUS_TIMEOUT_SECONDS,
        is_library_item=True,
        is_archived=False,
    )
    session = ClaudeCodeSession(FakeClaudeAgentClient(messages_per_query=[]))

    outcome = await execute_node(
        node,
        prompt=None,
        claude_session=session,
        repos_path=tmp_path,
        timeout_seconds=_GENEROUS_TIMEOUT_SECONDS,
    )

    assert outcome.success is True
    assert "через execute_node" in (outcome.script_stdout or "")


async def test_execute_node_raises_when_llm_node_has_no_prompt(tmp_path: Path) -> None:
    node = Node(
        created_by=uuid.uuid4(),
        name="n",
        node_type=NodeType.PLAIN_PROMPT,
        timeout_seconds=_GENEROUS_TIMEOUT_SECONDS,
        is_library_item=True,
        is_archived=False,
    )
    session = ClaudeCodeSession(FakeClaudeAgentClient(messages_per_query=[]))

    with pytest.raises(ValueError, match="prompt"):
        await execute_node(
            node,
            prompt=None,
            claude_session=session,
            repos_path=tmp_path,
            timeout_seconds=_GENEROUS_TIMEOUT_SECONDS,
        )


async def _make_task_with_node_log(db_session: AsyncSession) -> tuple[Task, NodeLog]:
    user = User(email=f"{uuid.uuid4()}@example.com", role=UserRole.USER)
    db_session.add(user)
    await db_session.flush()
    task = Task(
        code=f"RR-{uuid.uuid4().hex[:5]}",
        title="t",
        description="d",
        created_by=user.id,
        status=TaskStatus.IN_PROGRESS,
    )
    db_session.add(task)
    await db_session.flush()
    node_log = NodeLog(
        task_id=task.id,
        trigger_type=NodeLogTriggerType.PIPELINE,
        status=NodeLogStatus.RUNNING,
    )
    db_session.add(node_log)
    await db_session.flush()
    return task, node_log


class TestPlanAcceptedMode:
    """Раздел 9.4: после хода принятого плана сессия выходит из `plan` в выбранный режим."""

    @pytest.mark.parametrize(
        ("task_mode", "session_mode"),
        [
            (None, "acceptEdits"),
            (PermissionMode.ACCEPT_EDITS, "acceptEdits"),
            (PermissionMode.DEFAULT, "default"),
        ],
        ids=["unset", "auto", "confirm_each"],
    )
    async def test_switches_after_turn(
        self,
        db_session: AsyncSession,
        task_mode: PermissionMode | None,
        session_mode: str,
    ) -> None:
        task, node_log = await _make_task_with_node_log(db_session)

        async def _accept_plan() -> None:
            node_log.status = NodeLogStatus.SUCCESS
            task.current_permission_mode = task_mode
            await db_session.commit()

        fake = FakeClaudeAgentClient(
            messages_per_query=[[make_result_message()]],
            on_query=_accept_plan,
        )

        outcome = await execute_plan_prompt_node(
            ClaudeCodeSession(fake),
            "составь план",
            db_session=db_session,
            node_log_id=node_log.id,
            timeout_seconds=_GENEROUS_TIMEOUT_SECONDS,
        )

        assert outcome.success is True
        assert fake.permission_modes == ["plan", session_mode]

    async def test_not_accepted_stays_in_plan(self, db_session: AsyncSession) -> None:
        _task, node_log = await _make_task_with_node_log(db_session)
        fake = FakeClaudeAgentClient(messages_per_query=[[make_result_message()]])

        await execute_plan_prompt_node(
            ClaudeCodeSession(fake),
            "составь план",
            db_session=db_session,
            node_log_id=node_log.id,
            timeout_seconds=_GENEROUS_TIMEOUT_SECONDS,
        )

        assert fake.permission_modes == ["plan"]


async def test_execute_plan_prompt_node_fails_when_plan_never_accepted(
    db_session: AsyncSession,
) -> None:
    _task, node_log = await _make_task_with_node_log(db_session)
    fake = FakeClaudeAgentClient(messages_per_query=[[make_result_message()]])
    session = ClaudeCodeSession(fake)

    outcome = await execute_plan_prompt_node(
        session,
        "составь план",
        db_session=db_session,
        node_log_id=node_log.id,
        timeout_seconds=_GENEROUS_TIMEOUT_SECONDS,
    )

    assert outcome.success is False
    assert outcome.error_message is not None


async def test_execute_plan_prompt_node_propagates_llm_error(db_session: AsyncSession) -> None:
    _task, node_log = await _make_task_with_node_log(db_session)
    fake = FakeClaudeAgentClient(messages_per_query=[[make_result_message(is_error=True)]])
    session = ClaudeCodeSession(fake)

    outcome = await execute_plan_prompt_node(
        session,
        "составь план",
        db_session=db_session,
        node_log_id=node_log.id,
        timeout_seconds=_GENEROUS_TIMEOUT_SECONDS,
    )

    assert outcome.success is False


async def test_execute_node_dispatches_plan_prompt_type(
    db_session: AsyncSession,
    tmp_path: Path,
) -> None:
    _task, node_log = await _make_task_with_node_log(db_session)
    node = Node(
        created_by=uuid.uuid4(),
        name="n",
        node_type=NodeType.PLAN_PROMPT,
        timeout_seconds=_GENEROUS_TIMEOUT_SECONDS,
        is_library_item=False,
        is_archived=False,
    )

    async def _accept_plan() -> None:
        node_log.status = NodeLogStatus.SUCCESS
        await db_session.commit()

    fake = FakeClaudeAgentClient(
        messages_per_query=[[make_result_message()]],
        on_query=_accept_plan,
    )
    session = ClaudeCodeSession(fake)

    outcome = await execute_node(
        node,
        prompt="составь план",
        claude_session=session,
        repos_path=tmp_path,
        timeout_seconds=_GENEROUS_TIMEOUT_SECONDS,
        db_session=db_session,
        node_log_id=node_log.id,
    )

    assert outcome.success is True
    assert fake.permission_modes == ["plan", "acceptEdits"]


async def test_execute_node_plan_prompt_requires_db_session_and_node_log_id(
    tmp_path: Path,
) -> None:
    node = Node(
        created_by=uuid.uuid4(),
        name="n",
        node_type=NodeType.PLAN_PROMPT,
        timeout_seconds=_GENEROUS_TIMEOUT_SECONDS,
        is_library_item=False,
        is_archived=False,
    )
    session = ClaudeCodeSession(FakeClaudeAgentClient(messages_per_query=[]))

    with pytest.raises(ValueError, match="db_session"):
        await execute_node(
            node,
            prompt="составь план",
            claude_session=session,
            repos_path=tmp_path,
            timeout_seconds=_GENEROUS_TIMEOUT_SECONDS,
        )


class TestScriptRunnerImage:
    @pytest.mark.parametrize(
        ("node_image", "runner_image", "expected"),
        [(None, "settings:1", "settings:1"), ("own:1", None, "own:1"), (None, None, None)],
    )
    async def test_image_passed_to_runner(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        node_image: str | None,
        runner_image: str | None,
        expected: str | None,
    ) -> None:
        seen: list[str | None] = []

        async def fake_run(*, docker_image: str | None, **_: object) -> ScriptExecutionResult:
            seen.append(docker_image)
            return ScriptExecutionResult(exit_code=0, stdout="", stderr="", timed_out=False)

        monkeypatch.setattr(dispatch, "run_script_node", fake_run)
        node = Node(
            created_by=uuid.uuid4(),
            name="n",
            node_type=NodeType.SCRIPT,
            script_language=ScriptLanguage.BASH,
            script_content="echo",
            docker_image=node_image,
            timeout_seconds=_GENEROUS_TIMEOUT_SECONDS,
            is_library_item=True,
            is_archived=False,
        )

        await execute_script_node(node, repos_path=tmp_path, runner_image=runner_image)

        assert seen == [expected]


class TestPartialReply:
    """Раздел 6.4: полученная до таймаута часть ответа попадает в результат ноды."""

    async def test_kept_on_timeout(self) -> None:
        fake = FakeClaudeAgentClient(
            messages_per_query=[
                [
                    AssistantMessage(content=[TextBlock(text="часть ответа")], model="claude"),
                    make_result_message(),
                ],
            ],
        )
        fake.message_delay_seconds = 0.5
        session = ClaudeCodeSession(fake)

        outcome = await execute_llm_node_with_timeout(session, "hi", timeout_seconds=0.75)

        assert outcome.success is False
        assert outcome.llm_output_text == "часть ответа"
        assert session.take_partial_turn_text() is None

    async def test_no_leftover_after_full_turn(self) -> None:
        fake = FakeClaudeAgentClient(
            messages_per_query=[
                [
                    AssistantMessage(content=[TextBlock(text="ответ")], model="claude"),
                    make_result_message(),
                ],
            ],
        )
        session = ClaudeCodeSession(fake)

        outcome = await execute_llm_node_with_timeout(session, "hi", timeout_seconds=5)

        assert outcome.llm_output_text == "ответ"
        assert session.take_partial_turn_text() is None


class TestRecordSdkFailure:
    """Раздел 17.2: в `app_logs` — только ошибки взаимодействия с SDK."""

    @pytest.mark.parametrize(
        ("outcome", "logged", "message_part"),
        [
            (NodeExecutionOutcome(success=True), False, None),
            (NodeExecutionOutcome(success=False, error_message="Код возврата 1"), False, None),
            (
                NodeExecutionOutcome(
                    success=False,
                    is_transient=False,
                    error_message="authentication_failed",
                ),
                True,
                "authentication_failed",
            ),
            (
                NodeExecutionOutcome(
                    success=False,
                    session_lost=True,
                    error_message="Сбой сессии",
                    error_details="exit code 1",
                ),
                True,
                "exit code 1",
            ),
        ],
        ids=["success", "script_or_timeout", "permanent", "cli_crashed"],
    )
    async def test_logged(
        self,
        monkeypatch: pytest.MonkeyPatch,
        outcome: NodeExecutionOutcome,
        logged: bool,
        message_part: str | None,
    ) -> None:
        calls: list[dict[str, object]] = []

        async def record(**kwargs: object) -> None:
            calls.append(kwargs)

        monkeypatch.setattr(dispatch, "write_app_log", record)
        task_id = uuid.uuid4()

        await record_sdk_failure(outcome, task_id=task_id, node_id=None, source="test")

        assert len(calls) == (1 if logged else 0)
        if logged:
            assert calls[0]["task_id"] == task_id
            assert message_part is not None
            assert message_part in str(calls[0]["message"])


class TestScriptTaskPaths:
    """Раздел 11.4: текст скрипта не шаблонизируется — пути задачи приходят в окружении."""

    async def test_script_saves_artifact(self, tmp_path: Path, user_files_root: Path) -> None:
        repos_path = tmp_path / "repos" / "RR-55555"
        repos_path.mkdir(parents=True)
        node = Node(
            created_by=uuid.uuid4(),
            name="n",
            node_type=NodeType.SCRIPT,
            script_language=ScriptLanguage.PYTHON,
            script_content=(
                "import os\n"
                "path = os.path.join(os.environ['TASK_ARTIFACTS_PATH'], 'report.txt')\n"
                "open(path, 'w').write(os.environ['TASK_REPOS_PATH'])\n"
            ),
            timeout_seconds=_GENEROUS_TIMEOUT_SECONDS,
            is_library_item=True,
            is_archived=False,
        )

        outcome = await execute_script_node(
            node,
            repos_path=repos_path,
            # Переменная задачи с тем же именем путь не подменяет.
            env={"TASK_ARTIFACTS_PATH": "/tmp"},
        )

        assert outcome.success is True, outcome.error_message
        assert (user_files_root / "RR-55555" / "report.txt").read_text() == str(repos_path)
