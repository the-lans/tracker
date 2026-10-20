"""Тесты `tasks/session_worker.py` — полный прогон задачи одним таском сессии.

Реальный `ClaudeSDKClient` подменён `FakeClaudeAgentClient`, собственные
сессии БД и Redis воркера — тестовыми (в общей откатываемой транзакции).
Origin репозитория — локальный bare-репозиторий, как в `test_git_ops.py`.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
import sqlalchemy as sa
from claude_agent_sdk import ClaudeAgentOptions, PermissionResultAllow
from claude_agent_sdk.types import ToolPermissionContext

from clients.claude_agent import REMOTE_CONTROL_EXTRA_ARG
from db.models.enums import (
    McpAuthType,
    McpIsolationMode,
    MergeStatus,
    NodeLogStatus,
    NodeLogTriggerType,
    NodeType,
    RemoteControlStatus,
    RepositoryRole,
    TaskStatus,
    UserRole,
)
from db.models.llm import LlmAccount
from db.models.logs import NodeLog
from db.models.mcp import McpServer
from db.models.pipelines import Node, Pipeline, TaskNode
from db.models.repositories import Repository, Template, TemplateMcpServer
from db.models.tasks import Task, TaskRepository
from db.models.users import User
from services.claude_config import DEFAULT_HISTORY_RETENTION_DAYS
from services.crypto import encrypt
from services.manual_queue import enqueue_freeform_prompt_run
from services.session_context import clear_task_session_context
from services.session_heartbeat import is_session_alive
from services.task_control import (
    TaskControlCommand,
    consume_bridge_reconnect,
    consume_task_control,
    read_task_control,
    request_bridge_reconnect,
    request_task_control,
)
from services.task_status import transition_task_status
from services.task_workspace import build_branch_name
from tasks import session_worker
from tests.fakes import FakeClaudeAgentClient, make_result_message
from tests.worker_support import GIT_AUTHOR_ARGS, WorkerEnv, init_bare_origin, run_command

if TYPE_CHECKING:
    from claude_agent_sdk import Message
    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncSession

_REPOSITORY_NAME = "backend"


async def _make_task(
    db_session: AsyncSession,
    *,
    status: TaskStatus,
    origin: Path | None = None,
) -> Task:
    user = User(email=f"{uuid.uuid4()}@example.com", role=UserRole.USER)
    pipeline = Pipeline(name="p", is_archived=False)
    db_session.add_all([user, pipeline])
    await db_session.flush()
    task = Task(
        code=f"RR-{uuid.uuid4().hex[:5]}",
        title="t",
        description="d",
        created_by=user.id,
        pipeline_id=pipeline.id,
        status=status,
    )
    db_session.add(task)
    await db_session.flush()
    if origin is not None:
        repository = Repository(
            name=_REPOSITORY_NAME,
            git_url=str(origin),
            deploy_key_encrypted=encrypt("не используется"),
        )
        db_session.add(repository)
        await db_session.flush()
        db_session.add(
            TaskRepository(
                task_id=task.id,
                repository_id=repository.id,
                role=RepositoryRole.READ_WRITE,
                branch_name=build_branch_name(task.code),
                base_branch="main",
            ),
        )
        await db_session.flush()
    return task


async def _add_node(
    db_session: AsyncSession,
    task: Task,
    *,
    order_index: int,
    node_type: NodeType = NodeType.PLAIN_PROMPT,
) -> Node:
    node = Node(
        pipeline_id=task.pipeline_id,
        order_index=order_index,
        name=f"node-{order_index}",
        node_type=node_type,
        prompt_template=f"шаг {order_index}" if node_type is NodeType.PLAIN_PROMPT else None,
        timeout_seconds=60,
        max_retries=1,
        retry_base_delay_seconds=0,
        is_skipped=False,
        is_library_item=False,
        is_archived=False,
    )
    db_session.add(node)
    await db_session.flush()
    db_session.add(TaskNode(task_id=task.id, node_id=node.id, order_index=order_index))
    await db_session.flush()
    return node


def _results(count: int) -> list[list[Message]]:
    return [[make_result_message(session_id="sess-worker")] for _ in range(count)]


async def _run_worker(task: Task, **kwargs: Any) -> None:
    await session_worker._run_task_session_async(
        task.id,
        start_after_order_index=kwargs.get("start_after_order_index"),
        continuation=kwargs.get("continuation", False),
    )


async def test_completed_pipeline_pushes_work_branch_and_finishes_task(
    db_session: AsyncSession,
    worker_env: WorkerEnv,
    tmp_path: Path,
) -> None:
    origin = init_bare_origin(tmp_path)
    task = await _make_task(db_session, status=TaskStatus.QUEUED, origin=origin)
    await _add_node(db_session, task, order_index=0)
    repo_dir = worker_env.repos_root / task.code / _REPOSITORY_NAME

    async def agent_commits_work() -> None:
        (repo_dir / "feature.txt").write_text("результат\n")
        run_command("git", "add", "feature.txt", cwd=repo_dir)
        run_command("git", *GIT_AUTHOR_ARGS, "commit", "-m", "работа агента", cwd=repo_dir)

    worker_env.client = FakeClaudeAgentClient(
        messages_per_query=_results(1),
        on_query=agent_commits_work,
    )

    await _run_worker(task)

    await db_session.refresh(task)
    assert task.status is TaskStatus.DONE
    assert task.session_id == "sess-worker"
    branch = build_branch_name(task.code)
    assert "feature.txt" in run_command("git", "ls-tree", "--name-only", branch, cwd=origin)
    task_repository = (
        await db_session.execute(sa.select(TaskRepository).where(TaskRepository.task_id == task.id))
    ).scalar_one()
    assert task_repository.merge_status is MergeStatus.PUSHED


async def test_crash_during_session_fails_task_instead_of_hanging(
    db_session: AsyncSession,
    worker_env: WorkerEnv,
) -> None:
    task = await _make_task(db_session, status=TaskStatus.QUEUED)
    await _add_node(db_session, task, order_index=0)
    await db_session.commit()

    async def sdk_crashes() -> None:
        raise RuntimeError("процесс claude упал")

    worker_env.client.connect = sdk_crashes  # type: ignore[method-assign]

    await _run_worker(task)

    await db_session.refresh(task)
    assert task.status is TaskStatus.FAILED
    assert task.last_failed_order_index == 0


async def test_worker_skips_task_already_claimed_by_another_worker(
    db_session: AsyncSession,
    worker_env: WorkerEnv,
) -> None:
    task = await _make_task(db_session, status=TaskStatus.IN_PROGRESS)
    await _add_node(db_session, task, order_index=0)

    await _run_worker(task)

    await db_session.refresh(task)
    assert task.status is TaskStatus.IN_PROGRESS
    assert worker_env.client.connected is False


async def test_clear_context_hands_session_over_to_continuation_task(
    db_session: AsyncSession,
    worker_env: WorkerEnv,
) -> None:
    task = await _make_task(db_session, status=TaskStatus.QUEUED)
    await _add_node(db_session, task, order_index=0)
    await _add_node(db_session, task, order_index=1, node_type=NodeType.CLEAR_CONTEXT)
    await _add_node(db_session, task, order_index=2)
    worker_env.client = FakeClaudeAgentClient(messages_per_query=_results(1))

    await _run_worker(task)

    assert worker_env.enqueued == [
        ([str(task.id)], {"start_after_order_index": 1, "continuation": True}),
    ]

    worker_env.client = FakeClaudeAgentClient(messages_per_query=_results(1))
    await _run_worker(task, start_after_order_index=1, continuation=True)

    await db_session.refresh(task)
    assert task.status is TaskStatus.DONE
    assert worker_env.client.queries == ["шаг 2"]


async def test_restart_after_failure_reruns_failed_node_only(
    db_session: AsyncSession,
    worker_env: WorkerEnv,
) -> None:
    task = await _make_task(db_session, status=TaskStatus.FAILED)
    done_node = await _add_node(db_session, task, order_index=0)
    await _add_node(db_session, task, order_index=1)
    task.last_failed_order_index = 1
    db_session.add(
        NodeLog(
            task_id=task.id,
            node_id=done_node.id,
            trigger_type=NodeLogTriggerType.PIPELINE,
            status=NodeLogStatus.SUCCESS,
        ),
    )
    await db_session.flush()
    worker_env.client = FakeClaudeAgentClient(messages_per_query=_results(1))

    await _run_worker(task, start_after_order_index=0)

    await db_session.refresh(task)
    assert task.status is TaskStatus.DONE
    assert worker_env.client.queries == ["шаг 1"]


async def _enqueue_freeform(db_session: AsyncSession, task: Task, text: str) -> None:
    await enqueue_freeform_prompt_run(
        db_session,
        task_id=task.id,
        raw_prompt_text=text,
        requested_by=task.created_by,
    )


async def test_manual_request_runs_before_next_pipeline_node(
    db_session: AsyncSession,
    worker_env: WorkerEnv,
) -> None:
    """Раздел 7.3: очередь FIFO обрабатывается «прежде, чем переходить к
    следующей ноде пайплайна»."""
    task = await _make_task(db_session, status=TaskStatus.QUEUED)
    await _add_node(db_session, task, order_index=0)
    await _add_node(db_session, task, order_index=1)

    async def user_sends_prompts_during_first_node() -> None:
        if len(worker_env.client.queries) == 1:
            await _enqueue_freeform(db_session, task, "первый вопрос")
            await _enqueue_freeform(db_session, task, "второй вопрос")

    worker_env.client = FakeClaudeAgentClient(
        messages_per_query=_results(4),
        on_query=user_sends_prompts_during_first_node,
    )

    await _run_worker(task)

    assert worker_env.client.queries == ["шаг 0", "первый вопрос", "второй вопрос", "шаг 1"]
    await db_session.refresh(task)
    assert task.status is TaskStatus.DONE


async def test_manual_request_queued_during_last_node_runs_before_done(
    db_session: AsyncSession,
    worker_env: WorkerEnv,
) -> None:
    task = await _make_task(db_session, status=TaskStatus.QUEUED)
    await _add_node(db_session, task, order_index=0)

    async def user_sends_prompt() -> None:
        if len(worker_env.client.queries) == 1:
            await _enqueue_freeform(db_session, task, "вопрос напоследок")

    worker_env.client = FakeClaudeAgentClient(
        messages_per_query=_results(2),
        on_query=user_sends_prompt,
    )

    await _run_worker(task)

    assert worker_env.client.queries == ["шаг 0", "вопрос напоследок"]
    await db_session.refresh(task)
    assert task.status is TaskStatus.DONE


def _patch_pause_wait(
    monkeypatch: pytest.MonkeyPatch,
    on_wait: Any,
) -> list[TaskStatus]:
    """Пока воркер стоит на паузе, он ждёт сигнала и не трогает БД — здесь
    и выполняются действия «пользователя»."""
    observed: list[TaskStatus] = []

    async def fake_wait(_redis: Any, _task_id: uuid.UUID, *, timeout: float | None) -> bool:
        await on_wait(observed)
        return True

    monkeypatch.setattr(session_worker, "wait_for_task_signal", fake_wait)
    return observed


async def test_pause_holds_session_runs_manual_prompts_and_resumes(
    db_session: AsyncSession,
    worker_env: WorkerEnv,
    redis_client: Redis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = await _make_task(db_session, status=TaskStatus.QUEUED)
    await _add_node(db_session, task, order_index=0)
    await _add_node(db_session, task, order_index=1)

    async def user_presses_pause() -> None:
        if len(worker_env.client.queries) == 1:
            await request_task_control(redis_client, task.id, TaskControlCommand.PAUSE)

    async def while_paused(observed: list[TaskStatus]) -> None:
        await db_session.refresh(task)
        observed.append(task.status)
        await _enqueue_freeform(db_session, task, "вопрос на паузе")
        await request_task_control(redis_client, task.id, TaskControlCommand.RESUME)

    observed = _patch_pause_wait(monkeypatch, while_paused)
    worker_env.client = FakeClaudeAgentClient(
        messages_per_query=_results(3),
        on_query=user_presses_pause,
    )

    await _run_worker(task)

    assert observed == [TaskStatus.PAUSED]
    assert worker_env.client.queries == ["шаг 0", "вопрос на паузе", "шаг 1"]
    await db_session.refresh(task)
    assert task.status is TaskStatus.DONE
    assert await read_task_control(redis_client, task.id) is None


async def test_stop_while_paused_fails_task_at_next_node(
    db_session: AsyncSession,
    worker_env: WorkerEnv,
    redis_client: Redis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = await _make_task(db_session, status=TaskStatus.QUEUED)
    await _add_node(db_session, task, order_index=0)
    await _add_node(db_session, task, order_index=1)

    async def user_presses_pause() -> None:
        await request_task_control(redis_client, task.id, TaskControlCommand.PAUSE)

    async def while_paused(_observed: list[TaskStatus]) -> None:
        await request_task_control(redis_client, task.id, TaskControlCommand.STOP)

    _patch_pause_wait(monkeypatch, while_paused)
    worker_env.client = FakeClaudeAgentClient(
        messages_per_query=_results(1),
        on_query=user_presses_pause,
    )

    await _run_worker(task)

    await db_session.refresh(task)
    assert task.status is TaskStatus.FAILED
    # «Перезапустить с текущей ноды» продолжит с ещё не выполненной ноды.
    assert task.last_failed_order_index == 1
    assert worker_env.client.queries == ["шаг 0"]


async def test_stop_during_node_interrupts_session_and_fails_task(
    db_session: AsyncSession,
    worker_env: WorkerEnv,
    redis_client: Redis,
) -> None:
    task = await _make_task(db_session, status=TaskStatus.QUEUED)
    await _add_node(db_session, task, order_index=0)
    await _add_node(db_session, task, order_index=1)
    pending: list[asyncio.Future[None]] = []

    async def press_stop_soon() -> None:
        await asyncio.sleep(0.3)
        await request_task_control(redis_client, task.id, TaskControlCommand.STOP)
        worker_env.client.message_delay_seconds = 0

    async def long_running_node() -> None:
        worker_env.client.message_delay_seconds = 30
        pending.append(asyncio.ensure_future(press_stop_soon()))

    worker_env.client = FakeClaudeAgentClient(
        messages_per_query=_results(1),
        on_query=long_running_node,
    )

    await asyncio.wait_for(_run_worker(task), timeout=15)
    await asyncio.gather(*pending)

    await db_session.refresh(task)
    assert task.status is TaskStatus.FAILED
    assert task.last_failed_order_index == 0
    assert worker_env.client.interrupted is True
    statuses = (
        (await db_session.execute(sa.select(NodeLog.status).where(NodeLog.task_id == task.id)))
        .scalars()
        .all()
    )
    assert statuses == [NodeLogStatus.STOPPED]


def _push_conflicting_base_update(tmp_path: Path, origin: Path) -> None:
    updater_dir = tmp_path / "updater"
    run_command("git", "clone", str(origin), str(updater_dir), cwd=tmp_path)
    (updater_dir / "README.md").write_text("изменение родительской задачи\n")
    run_command("git", "add", "README.md", cwd=updater_dir)
    run_command("git", *GIT_AUTHOR_ARGS, "commit", "-m", "смерджен родитель", cwd=updater_dir)
    run_command("git", "push", "origin", "main", cwd=updater_dir)


@pytest.mark.parametrize("agent_resolves", [True, False])
async def test_rebase_conflict_is_resolved_by_agent_before_next_node(
    db_session: AsyncSession,
    worker_env: WorkerEnv,
    tmp_path: Path,
    agent_resolves: bool,
) -> None:
    """Раздел 14.1: `rebase_conflict -> in_progress (после автообработки)`,
    иначе `-> failed`."""
    origin = init_bare_origin(tmp_path)
    task = await _make_task(db_session, status=TaskStatus.QUEUED, origin=origin)
    await _add_node(db_session, task, order_index=0)
    await _add_node(db_session, task, order_index=1)
    repo_dir = worker_env.repos_root / task.code / _REPOSITORY_NAME

    async def agent_and_periodic_task() -> None:
        call = len(worker_env.client.queries)
        if call == 1:
            # Нода 0: агент коммитит, а тем временем родителя смерджили и
            # периодическая задача поймала конфликт ребейза.
            (repo_dir / "README.md").write_text("изменение дочерней задачи\n")
            run_command("git", "add", "README.md", cwd=repo_dir)
            run_command("git", *GIT_AUTHOR_ARGS, "commit", "-m", "работа агента", cwd=repo_dir)
            _push_conflicting_base_update(tmp_path, origin)
            await transition_task_status(
                db_session,
                task_id=task.id,
                from_status=TaskStatus.IN_PROGRESS,
                to_status=TaskStatus.REBASE_CONFLICT,
            )
        elif call == 2 and agent_resolves:
            run_command("git", "fetch", "origin", "main", cwd=repo_dir)
            subprocess.run(
                ["git", *GIT_AUTHOR_ARGS, "rebase", "origin/main"],
                cwd=repo_dir,
                capture_output=True,
                check=False,
            )
            (repo_dir / "README.md").write_text("обе правки объединены\n")
            run_command("git", "add", "README.md", cwd=repo_dir)
            run_command(
                "git",
                *GIT_AUTHOR_ARGS,
                "-c",
                "core.editor=true",
                "rebase",
                "--continue",
                cwd=repo_dir,
            )

    worker_env.client = FakeClaudeAgentClient(
        messages_per_query=_results(3),
        on_query=agent_and_periodic_task,
    )

    await _run_worker(task)

    await db_session.refresh(task)
    if agent_resolves:
        assert task.status is TaskStatus.DONE
        assert worker_env.client.queries[2] == "шаг 1"
        branch = build_branch_name(task.code)
        tree = run_command("git", "show", f"{branch}:README.md", cwd=origin)
        assert tree == "обе правки объединены\n"
    else:
        assert task.status is TaskStatus.FAILED
        assert task.last_failed_order_index == 1
        assert len(worker_env.client.queries) == 2


async def _refreshed_status(db_session: AsyncSession, task: Task) -> TaskStatus:
    await db_session.refresh(task)
    return task.status


class TestConflictAfterRestart:
    async def test_resolved_before_nodes(
        self,
        db_session: AsyncSession,
        worker_env: WorkerEnv,
        tmp_path: Path,
    ) -> None:
        """
        После неудачной автообработки и «Перезапустить» статус уже не
        `rebase_conflict`, но ветка не перебазирована — её нельзя пушить как есть.
        """
        origin = init_bare_origin(tmp_path)
        task = await _make_task(db_session, status=TaskStatus.QUEUED, origin=origin)
        await _add_node(db_session, task, order_index=0)
        await _add_node(db_session, task, order_index=1)
        repo_dir = worker_env.repos_root / task.code / _REPOSITORY_NAME

        async def conflict_appears_and_agent_gives_up() -> None:
            if len(worker_env.client.queries) != 1:
                return
            (repo_dir / "README.md").write_text("изменение дочерней задачи\n")
            run_command("git", "add", "README.md", cwd=repo_dir)
            run_command("git", *GIT_AUTHOR_ARGS, "commit", "-m", "работа агента", cwd=repo_dir)
            _push_conflicting_base_update(tmp_path, origin)
            # Как `gitlab_sync.rebase_child_task_repositories_on_parent_merge`.
            await db_session.execute(
                sa.update(TaskRepository)
                .where(TaskRepository.task_id == task.id)
                .values(merge_status=MergeStatus.CONFLICT),
            )
            await transition_task_status(
                db_session,
                task_id=task.id,
                from_status=TaskStatus.IN_PROGRESS,
                to_status=TaskStatus.REBASE_CONFLICT,
            )

        worker_env.client = FakeClaudeAgentClient(
            messages_per_query=_results(2),
            on_query=conflict_appears_and_agent_gives_up,
        )
        await _run_worker(task)
        assert await _refreshed_status(db_session, task) is TaskStatus.FAILED
        assert task.last_failed_order_index == 1

        async def agent_resolves_on_first_query() -> None:
            if len(worker_env.client.queries) != 1:
                return
            run_command("git", "fetch", "origin", "main", cwd=repo_dir)
            subprocess.run(
                ["git", *GIT_AUTHOR_ARGS, "rebase", "origin/main"],
                cwd=repo_dir,
                capture_output=True,
                check=False,
            )
            (repo_dir / "README.md").write_text("обе правки объединены\n")
            run_command("git", "add", "README.md", cwd=repo_dir)
            run_command(
                "git",
                *GIT_AUTHOR_ARGS,
                "-c",
                "core.editor=true",
                "rebase",
                "--continue",
                cwd=repo_dir,
            )

        worker_env.client = FakeClaudeAgentClient(
            messages_per_query=_results(2),
            on_query=agent_resolves_on_first_query,
        )
        await _run_worker(task, start_after_order_index=0)

        assert await _refreshed_status(db_session, task) is TaskStatus.DONE
        assert "rebase" in worker_env.client.queries[0]
        assert worker_env.client.queries[1] == "шаг 1"
        branch = build_branch_name(task.code)
        merged = run_command("git", "show", f"{branch}:README.md", cwd=origin)
        assert merged == "обе правки объединены\n"


class TestPauseRace:
    async def test_survives_concurrent_conflict(
        self,
        db_session: AsyncSession,
        worker_env: WorkerEnv,
        redis_client: Redis,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """
        Периодическая задача меняет статус параллельно с воркером: проигранный
        compare-and-swap паузы/продолжения не должен валить задачу в `failed`.
        """
        task = await _make_task(db_session, status=TaskStatus.QUEUED)
        await _add_node(db_session, task, order_index=0)
        await _add_node(db_session, task, order_index=1)
        raced: list[TaskStatus] = []

        async def periodic_task_marks_conflict(from_status: TaskStatus) -> None:
            raced.append(from_status)
            await transition_task_status(
                db_session,
                task_id=task.id,
                from_status=from_status,
                to_status=TaskStatus.REBASE_CONFLICT,
            )

        real_consume = consume_task_control
        real_read = read_task_control

        async def racing_consume(
            redis: Any,
            task_id: uuid.UUID,
            command: TaskControlCommand,
        ) -> bool:
            if command is TaskControlCommand.PAUSE and not raced:
                await periodic_task_marks_conflict(TaskStatus.IN_PROGRESS)
            return await real_consume(redis, task_id, command)

        async def racing_read(redis: Any, task_id: uuid.UUID) -> TaskControlCommand | None:
            command = await real_read(redis, task_id)
            if command is TaskControlCommand.RESUME and len(raced) == 1:
                await periodic_task_marks_conflict(TaskStatus.PAUSED)
            return command

        monkeypatch.setattr(session_worker, "consume_task_control", racing_consume)
        monkeypatch.setattr(session_worker, "read_task_control", racing_read)

        async def user_presses_pause() -> None:
            if len(worker_env.client.queries) == 1:
                await request_task_control(redis_client, task.id, TaskControlCommand.PAUSE)

        async def while_paused(_observed: list[TaskStatus]) -> None:
            await request_task_control(redis_client, task.id, TaskControlCommand.RESUME)

        _patch_pause_wait(monkeypatch, while_paused)
        worker_env.client = FakeClaudeAgentClient(
            messages_per_query=_results(2),
            on_query=user_presses_pause,
        )

        await _run_worker(task)

        assert raced == [TaskStatus.IN_PROGRESS, TaskStatus.PAUSED]
        await db_session.refresh(task)
        assert task.status is TaskStatus.DONE
        assert worker_env.client.queries == ["шаг 0", "шаг 1"]


class TestQuestionDuringPausedPrompt:
    async def test_awaiting_input_then_back_to_paused(
        self,
        db_session: AsyncSession,
        worker_env: WorkerEnv,
        redis_client: Redis,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """
        Раздел 14.2, 14.3: ручной промт на паузе спрашивает пользователя —
        задача уходит в `awaiting_input` и возвращается на паузу.
        """
        task = await _make_task(db_session, status=TaskStatus.QUEUED)
        await _add_node(db_session, task, order_index=0)
        await _add_node(db_session, task, order_index=1)
        statuses_while_asking: list[TaskStatus] = []
        answers: list[str] = []

        async def user_answers(_redis: Any, _task_id: uuid.UUID, *, timeout: float | None) -> bool:
            await db_session.refresh(task)
            statuses_while_asking.append(task.status)
            pending = await db_session.scalar(
                sa.select(NodeLog).where(NodeLog.status == NodeLogStatus.AWAITING_DECISION),
            )
            assert pending is not None
            pending.user_input_text = "main"
            await db_session.commit()
            return True

        monkeypatch.setattr("services.plan_mode.wait_for_task_signal", user_answers)

        async def agent_behaviour() -> None:
            if len(worker_env.client.queries) == 1:
                await request_task_control(redis_client, task.id, TaskControlCommand.PAUSE)
            if worker_env.client.queries[-1] == "вопрос на паузе":
                can_use_tool = worker_env.options[0].can_use_tool
                assert can_use_tool is not None
                result = await can_use_tool(
                    "AskUserQuestion",
                    {"question": "Какую базу?", "options": ["main", "dev"]},
                    ToolPermissionContext(),
                )
                assert isinstance(result, PermissionResultAllow)
                assert result.updated_input is not None
                answers.append(result.updated_input["answer"])

        async def while_paused(observed: list[TaskStatus]) -> None:
            await db_session.refresh(task)
            observed.append(task.status)
            if len(observed) == 1:
                await _enqueue_freeform(db_session, task, "вопрос на паузе")
            else:
                await request_task_control(redis_client, task.id, TaskControlCommand.RESUME)

        observed = _patch_pause_wait(monkeypatch, while_paused)
        worker_env.client = FakeClaudeAgentClient(
            messages_per_query=_results(3),
            on_query=agent_behaviour,
        )

        await _run_worker(task)

        assert statuses_while_asking == [TaskStatus.AWAITING_INPUT]
        assert answers == ["main"]
        assert observed == [TaskStatus.PAUSED, TaskStatus.PAUSED]
        await db_session.refresh(task)
        assert task.status is TaskStatus.DONE


class TestBridgeReconnect:
    async def test_resumes_with_bridge(
        self,
        db_session: AsyncSession,
        worker_env: WorkerEnv,
        redis_client: Redis,
    ) -> None:
        """Раздел 6.5: «Переподключить» пересоздаёт процесс CLI между нодами."""
        task = await _make_task(db_session, status=TaskStatus.QUEUED)
        await _add_node(db_session, task, order_index=0)
        await _add_node(db_session, task, order_index=1)

        async def user_presses_reconnect() -> None:
            await request_bridge_reconnect(redis_client, task.id)

        first = FakeClaudeAgentClient(
            messages_per_query=_results(1),
            on_query=user_presses_reconnect,
        )
        second = FakeClaudeAgentClient(messages_per_query=_results(1))
        worker_env.queued_clients = [first, second]

        await _run_worker(task)

        assert first.queries == ["шаг 0"]
        assert first.disconnected is True
        assert second.queries == ["шаг 1"]
        reconnect_options = worker_env.options[1]
        assert reconnect_options.resume == "sess-worker"
        assert REMOTE_CONTROL_EXTRA_ARG in reconnect_options.extra_args
        await db_session.refresh(task)
        assert task.status is TaskStatus.DONE
        assert task.remote_control_status is RemoteControlStatus.CONNECTED


    async def test_last_node_request_dropped(
        self,
        db_session: AsyncSession,
        worker_env: WorkerEnv,
        redis_client: Redis,
    ) -> None:
        """
        Точки между нодами больше не будет — запрос снимается вместе с
        прогоном, статус не остаётся `reconnecting`.
        """
        task = await _make_task(db_session, status=TaskStatus.QUEUED)
        await _add_node(db_session, task, order_index=0)

        async def user_presses_reconnect() -> None:
            task.remote_control_status = RemoteControlStatus.RECONNECTING
            await db_session.commit()
            await request_bridge_reconnect(redis_client, task.id)

        worker_env.client = FakeClaudeAgentClient(
            messages_per_query=_results(1),
            on_query=user_presses_reconnect,
        )

        await _run_worker(task)

        await db_session.refresh(task)
        assert task.status is TaskStatus.DONE
        assert task.remote_control_status is RemoteControlStatus.DISCONNECTED
        assert await consume_bridge_reconnect(redis_client, task.id) is False
        assert len(worker_env.options) == 1


class TestRestartAfterClearContext:
    async def test_opens_new_session_with_bridge(
        self,
        db_session: AsyncSession,
        worker_env: WorkerEnv,
    ) -> None:
        """Раздел 14.2, 11.5: после «Очистить контекст» перезапуск — новая сессия."""
        task = await _make_task(db_session, status=TaskStatus.FAILED)
        await _add_node(db_session, task, order_index=0)
        task.last_failed_order_index = 0
        task.session_id = "sess-old"
        await db_session.flush()
        await clear_task_session_context(db_session, task=task)
        worker_env.client = FakeClaudeAgentClient(messages_per_query=_results(1))

        await _run_worker(task, start_after_order_index=-1)

        [options] = worker_env.options
        assert options.resume is None
        assert REMOTE_CONTROL_EXTRA_ARG in options.extra_args
        await db_session.refresh(task)
        assert task.session_id == "sess-worker"
        assert task.status is TaskStatus.DONE


_ISOLATION_HEADER = "X-Tracker-Isolation-Path"


def _isolation_header(options: ClaudeAgentOptions) -> str:
    assert isinstance(options.mcp_servers, dict)
    config = options.mcp_servers["playwright"]
    assert config.get("type") == "http"
    headers = config.get("headers")
    assert isinstance(headers, dict)
    return str(headers[_ISOLATION_HEADER])


class TestStatefulMcpIsolation:
    """
    Раздел 21.2, сценарий 12 (решение 2026-10-20 — уровень backend): две
    задачи с одним MCP-сервером с состоянием получают каждая свою изоляцию
    профиля; соблюдать её на стороне сервера — дело администратора (10.2).
    """

    @pytest.mark.parametrize(
        ("isolation_mode", "path_template"),
        [
            (
                McpIsolationMode.PER_TASK_DATA_DIR,
                "{{task.repos_path}}/.mcp-profiles/{{mcp_server.name}}",
            ),
            (McpIsolationMode.ISOLATED_FLAG, None),
        ],
    )
    async def test_each_task_gets_own_profile(
        self,
        db_session: AsyncSession,
        worker_env: WorkerEnv,
        tmp_path: Path,
        isolation_mode: McpIsolationMode,
        path_template: str | None,
    ) -> None:
        server = McpServer(
            name="playwright",
            url="https://mcp.internal/playwright",
            auth_type=McpAuthType.NONE,
            auth_config_encrypted=encrypt(""),
            is_healthy=True,
            has_stateful_resource=True,
            isolation_mode=isolation_mode,
            isolation_path_template=path_template,
        )
        template = Template(name=f"tpl-{uuid.uuid4().hex[:6]}", files={})
        db_session.add_all([server, template])
        await db_session.flush()
        db_session.add(TemplateMcpServer(template_id=template.id, mcp_server_id=server.id))
        tasks = []
        for index in range(2):
            origin_dir = tmp_path / f"origin-{index}"
            origin_dir.mkdir()
            origin = init_bare_origin(origin_dir)
            task = await _make_task(db_session, status=TaskStatus.QUEUED, origin=origin)
            await _add_node(db_session, task, order_index=0)
            repository = await db_session.scalar(
                sa.select(Repository)
                .join(TaskRepository, TaskRepository.repository_id == Repository.id)
                .where(TaskRepository.task_id == task.id),
            )
            assert repository is not None
            repository.default_template_id = template.id
            tasks.append(task)
        await db_session.flush()

        for task in tasks:
            worker_env.client = FakeClaudeAgentClient(messages_per_query=_results(1))
            await _run_worker(task)

        headers = [_isolation_header(options) for options in worker_env.options]
        if isolation_mode is McpIsolationMode.PER_TASK_DATA_DIR:
            assert headers == [
                f"tracker/repos/{task.code}/.mcp-profiles/playwright" for task in tasks
            ]
        else:
            assert headers == ["ephemeral", "ephemeral"]
        for task in tasks:
            await db_session.refresh(task)
            assert task.status is TaskStatus.DONE


class TestNodeTimeoutWhileAwaitingDecision:
    async def test_task_fails_instead_of_hanging(
        self,
        db_session: AsyncSession,
        worker_env: WorkerEnv,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """
        Пользователь не принял план за `timeout_seconds` ноды: ход
        прерывается, ожидание решения в задаче SDK снимается, задача — `failed`,
        а не висит в `plan_review` или в `in_progress` без воркера.
        """
        task = await _make_task(db_session, status=TaskStatus.QUEUED)
        plan_node = await _add_node(db_session, task, order_index=0, node_type=NodeType.PLAN_PROMPT)
        plan_node.prompt_template = "Составь план"
        plan_node.timeout_seconds = 1
        await db_session.flush()
        sdk_handlers: list[asyncio.Task[Any]] = []

        async def user_never_answers(*_args: Any, **_kwargs: Any) -> bool:
            await asyncio.Event().wait()
            return False

        monkeypatch.setattr("services.plan_mode.wait_for_task_signal", user_never_answers)

        class HangingClient(FakeClaudeAgentClient):
            async def interrupt(self) -> None:
                self.message_delay_seconds = 0
                await super().interrupt()

        async def agent_exits_plan_mode() -> None:
            can_use_tool = worker_env.options[0].can_use_tool
            assert can_use_tool is not None
            # Как в SDK: callback разрешений живёт в своей задаче, не в ходе.
            sdk_handlers.append(
                asyncio.ensure_future(
                    can_use_tool("ExitPlanMode", {"plan": "1. Шаг"}, ToolPermissionContext()),
                ),
            )
            worker_env.client.message_delay_seconds = 30

        worker_env.client = HangingClient(
            messages_per_query=_results(1),
            on_query=agent_exits_plan_mode,
        )

        await asyncio.wait_for(_run_worker(task), timeout=30)

        await db_session.refresh(task)
        assert task.status is TaskStatus.FAILED
        assert task.last_failed_order_index == 0
        assert all(handler.done() for handler in sdk_handlers)


class TestHistoryRetention:
    async def test_set_before_session_starts(
        self,
        db_session: AsyncSession,
        worker_env: WorkerEnv,
        tmp_path: Path,
    ) -> None:
        """Раздел 6.4: CLI не должен удалить историю, пока задача существует."""
        config_dir = tmp_path / "llm-account"
        account = LlmAccount(label="main", claude_config_dir=str(config_dir))
        db_session.add(account)
        await db_session.flush()
        task = await _make_task(db_session, status=TaskStatus.QUEUED)
        task.llm_account_id = account.id
        await _add_node(db_session, task, order_index=0)
        worker_env.client = FakeClaudeAgentClient(messages_per_query=_results(1))

        await _run_worker(task)

        settings = json.loads((config_dir / "settings.json").read_text())
        assert settings["cleanupPeriodDays"] == DEFAULT_HISTORY_RETENTION_DAYS


class TestSessionHeartbeat:
    async def test_alive_during_run_cleared_after(
        self,
        db_session: AsyncSession,
        worker_env: WorkerEnv,
        redis_client: Redis,
    ) -> None:
        """Раздел 6.6: мониторинг моста видит воркер по пульсу."""
        task = await _make_task(db_session, status=TaskStatus.QUEUED)
        await _add_node(db_session, task, order_index=0)
        observed: list[bool] = []

        async def check_heartbeat() -> None:
            observed.append(await is_session_alive(redis_client, task.id))

        worker_env.client = FakeClaudeAgentClient(
            messages_per_query=_results(1),
            on_query=check_heartbeat,
        )

        await _run_worker(task)

        assert observed == [True]
        assert not await is_session_alive(redis_client, task.id)
