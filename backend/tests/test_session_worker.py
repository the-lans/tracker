"""Тесты `tasks/session_worker.py` — полный прогон задачи одним таском сессии.

Реальный `ClaudeSDKClient` подменён `FakeClaudeAgentClient`, собственные
сессии БД и Redis воркера — тестовыми (в общей откатываемой транзакции).
Origin репозитория — локальный bare-репозиторий, как в `test_git_ops.py`.
"""

from __future__ import annotations

import asyncio
import subprocess
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest
import sqlalchemy as sa

from db.models.enums import (
    MergeStatus,
    NodeLogStatus,
    NodeLogTriggerType,
    NodeType,
    RepositoryRole,
    TaskStatus,
    UserRole,
)
from db.models.logs import NodeLog
from db.models.pipelines import Node, Pipeline, TaskNode
from db.models.repositories import Repository
from db.models.tasks import Task, TaskRepository
from db.models.users import User
from services.crypto import encrypt
from services.manual_queue import enqueue_freeform_prompt_run
from services.task_control import (
    TaskControlCommand,
    consume_task_control,
    read_task_control,
    request_task_control,
)
from services.task_status import transition_task_status
from services.task_workspace import build_branch_name
from tasks import session_worker
from tests.fakes import FakeClaudeAgentClient, make_result_message

if TYPE_CHECKING:
    from claude_agent_sdk import Message
    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncSession

_GIT_AUTHOR_ARGS = ["-c", "user.email=test@example.com", "-c", "user.name=Test"]
_REPOSITORY_NAME = "backend"


def _run(*args: str, cwd: Path) -> str:
    result = subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True)
    return result.stdout


def _init_bare_origin(tmp_path: Path) -> Path:
    origin = tmp_path / "origin.git"
    _run("git", "init", "--bare", "--initial-branch=main", str(origin), cwd=tmp_path)
    seed_dir = tmp_path / "seed"
    _run("git", "clone", str(origin), str(seed_dir), cwd=tmp_path)
    (seed_dir / "README.md").write_text("исходный файл\n")
    _run("git", "add", "README.md", cwd=seed_dir)
    _run("git", *_GIT_AUTHOR_ARGS, "commit", "-m", "начальный коммит", cwd=seed_dir)
    _run("git", "push", "origin", "main", cwd=seed_dir)
    return origin


class _SharedSession:
    """`async with async_session_factory()` воркера — та же тестовая сессия."""

    def __init__(self, db_session: AsyncSession) -> None:
        self._db_session = db_session

    async def __aenter__(self) -> AsyncSession:
        return self._db_session

    async def __aexit__(self, *_exc_info: object) -> None:
        return None


class _KeepOpenRedis:
    """Воркер закрывает свой клиент Redis — тестовый закрывать нельзя."""

    def __init__(self, redis_client: Redis) -> None:
        self._redis_client = redis_client

    def __getattr__(self, name: str) -> Any:
        return getattr(self._redis_client, name)

    async def aclose(self) -> None:
        return None


@pytest.fixture
def worker_env(
    db_session: AsyncSession,
    redis_client: Redis,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> SimpleNamespace:
    """Подменяет зависимости воркера; ``env.client`` — фейк SDK следующего прогона."""
    env = SimpleNamespace(
        client=FakeClaudeAgentClient(messages_per_query=[]),
        repos_root=tmp_path / "repos",
        enqueued=[],
    )
    monkeypatch.setenv("TRACKER_REPOS_ROOT", str(env.repos_root))
    monkeypatch.setattr(session_worker, "async_session_factory", lambda: _SharedSession(db_session))
    monkeypatch.setattr(
        session_worker,
        "Redis",
        SimpleNamespace(from_url=lambda _url: _KeepOpenRedis(redis_client)),
    )
    monkeypatch.setattr(session_worker, "ClaudeSDKClient", lambda options: env.client)
    monkeypatch.setattr(
        session_worker.run_task_session,
        "apply_async",
        lambda args, kwargs, countdown: env.enqueued.append((args, kwargs)),
    )
    return env


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
    worker_env: SimpleNamespace,
    tmp_path: Path,
) -> None:
    origin = _init_bare_origin(tmp_path)
    task = await _make_task(db_session, status=TaskStatus.QUEUED, origin=origin)
    await _add_node(db_session, task, order_index=0)
    repo_dir = worker_env.repos_root / task.code / _REPOSITORY_NAME

    async def agent_commits_work() -> None:
        (repo_dir / "feature.txt").write_text("результат\n")
        _run("git", "add", "feature.txt", cwd=repo_dir)
        _run("git", *_GIT_AUTHOR_ARGS, "commit", "-m", "работа агента", cwd=repo_dir)

    worker_env.client = FakeClaudeAgentClient(
        messages_per_query=_results(1),
        on_query=agent_commits_work,
    )

    await _run_worker(task)

    await db_session.refresh(task)
    assert task.status is TaskStatus.DONE
    assert task.session_id == "sess-worker"
    branch = build_branch_name(task.code)
    assert "feature.txt" in _run("git", "ls-tree", "--name-only", branch, cwd=origin)
    task_repository = (
        await db_session.execute(sa.select(TaskRepository).where(TaskRepository.task_id == task.id))
    ).scalar_one()
    assert task_repository.merge_status is MergeStatus.PUSHED


async def test_crash_during_session_fails_task_instead_of_hanging(
    db_session: AsyncSession,
    worker_env: SimpleNamespace,
) -> None:
    task = await _make_task(db_session, status=TaskStatus.QUEUED)
    await _add_node(db_session, task, order_index=0)
    await db_session.commit()

    async def sdk_crashes() -> None:
        raise RuntimeError("процесс claude упал")

    worker_env.client.connect = sdk_crashes

    await _run_worker(task)

    await db_session.refresh(task)
    assert task.status is TaskStatus.FAILED
    assert task.last_failed_order_index == 0


async def test_worker_skips_task_already_claimed_by_another_worker(
    db_session: AsyncSession,
    worker_env: SimpleNamespace,
) -> None:
    task = await _make_task(db_session, status=TaskStatus.IN_PROGRESS)
    await _add_node(db_session, task, order_index=0)

    await _run_worker(task)

    await db_session.refresh(task)
    assert task.status is TaskStatus.IN_PROGRESS
    assert worker_env.client.connected is False


async def test_clear_context_hands_session_over_to_continuation_task(
    db_session: AsyncSession,
    worker_env: SimpleNamespace,
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
    worker_env: SimpleNamespace,
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
    worker_env: SimpleNamespace,
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
    worker_env: SimpleNamespace,
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
    worker_env: SimpleNamespace,
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
    worker_env: SimpleNamespace,
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
    worker_env: SimpleNamespace,
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
    _run("git", "clone", str(origin), str(updater_dir), cwd=tmp_path)
    (updater_dir / "README.md").write_text("изменение родительской задачи\n")
    _run("git", "add", "README.md", cwd=updater_dir)
    _run("git", *_GIT_AUTHOR_ARGS, "commit", "-m", "смерджен родитель", cwd=updater_dir)
    _run("git", "push", "origin", "main", cwd=updater_dir)


@pytest.mark.parametrize("agent_resolves", [True, False])
async def test_rebase_conflict_is_resolved_by_agent_before_next_node(
    db_session: AsyncSession,
    worker_env: SimpleNamespace,
    tmp_path: Path,
    agent_resolves: bool,
) -> None:
    """Раздел 14.1: `rebase_conflict -> in_progress (после автообработки)`,
    иначе `-> failed`."""
    origin = _init_bare_origin(tmp_path)
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
            _run("git", "add", "README.md", cwd=repo_dir)
            _run("git", *_GIT_AUTHOR_ARGS, "commit", "-m", "работа агента", cwd=repo_dir)
            _push_conflicting_base_update(tmp_path, origin)
            await transition_task_status(
                db_session,
                task_id=task.id,
                from_status=TaskStatus.IN_PROGRESS,
                to_status=TaskStatus.REBASE_CONFLICT,
            )
        elif call == 2 and agent_resolves:
            _run("git", "fetch", "origin", "main", cwd=repo_dir)
            subprocess.run(
                ["git", *_GIT_AUTHOR_ARGS, "rebase", "origin/main"],
                cwd=repo_dir,
                capture_output=True,
                check=False,
            )
            (repo_dir / "README.md").write_text("обе правки объединены\n")
            _run("git", "add", "README.md", cwd=repo_dir)
            _run(
                "git",
                *_GIT_AUTHOR_ARGS,
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
        tree = _run("git", "show", f"{branch}:README.md", cwd=origin)
        assert tree == "обе правки объединены\n"
    else:
        assert task.status is TaskStatus.FAILED
        assert task.last_failed_order_index == 1
        assert len(worker_env.client.queries) == 2


async def _refreshed_status(db_session: AsyncSession, task: Task) -> TaskStatus:
    await db_session.refresh(task)
    return task.status


async def test_unresolved_conflict_is_retried_on_restart_before_any_node(
    db_session: AsyncSession,
    worker_env: SimpleNamespace,
    tmp_path: Path,
) -> None:
    """После неудачной автообработки и «Перезапустить» статус уже не
    `rebase_conflict`, но ветка не перебазирована — её нельзя пушить как есть."""
    origin = _init_bare_origin(tmp_path)
    task = await _make_task(db_session, status=TaskStatus.QUEUED, origin=origin)
    await _add_node(db_session, task, order_index=0)
    await _add_node(db_session, task, order_index=1)
    repo_dir = worker_env.repos_root / task.code / _REPOSITORY_NAME

    async def conflict_appears_and_agent_gives_up() -> None:
        if len(worker_env.client.queries) != 1:
            return
        (repo_dir / "README.md").write_text("изменение дочерней задачи\n")
        _run("git", "add", "README.md", cwd=repo_dir)
        _run("git", *_GIT_AUTHOR_ARGS, "commit", "-m", "работа агента", cwd=repo_dir)
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
        _run("git", "fetch", "origin", "main", cwd=repo_dir)
        subprocess.run(
            ["git", *_GIT_AUTHOR_ARGS, "rebase", "origin/main"],
            cwd=repo_dir,
            capture_output=True,
            check=False,
        )
        (repo_dir / "README.md").write_text("обе правки объединены\n")
        _run("git", "add", "README.md", cwd=repo_dir)
        _run(
            "git",
            *_GIT_AUTHOR_ARGS,
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
    assert _run("git", "show", f"{branch}:README.md", cwd=origin) == "обе правки объединены\n"


async def test_pause_and_resume_survive_concurrent_rebase_conflict(
    db_session: AsyncSession,
    worker_env: SimpleNamespace,
    redis_client: Redis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Периодическая задача меняет статус параллельно с воркером: проигранный
    compare-and-swap паузы/продолжения не должен валить задачу в `failed`."""
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

    async def racing_consume(redis: Any, task_id: uuid.UUID, command: TaskControlCommand) -> bool:
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
