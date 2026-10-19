"""Тесты `tasks/session_worker.py` — полный прогон задачи одним таском сессии.

Реальный `ClaudeSDKClient` подменён `FakeClaudeAgentClient`, собственные
сессии БД и Redis воркера — тестовыми (в общей откатываемой транзакции).
Origin репозитория — локальный bare-репозиторий, как в `test_git_ops.py`.
"""

from __future__ import annotations

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
