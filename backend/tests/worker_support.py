"""
Общая обвязка тестов воркера сессии — не файл с тестами (как `fakes.py`).

Реальный `ClaudeSDKClient` подменяется фейком, собственные сессии БД и
Redis воркера — тестовыми (в общей откатываемой транзакции). Origin
репозитория — локальный bare-репозиторий, как в `test_git_ops.py`.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

from tasks import session_worker
from tests.fakes import FakeClaudeAgentClient

if TYPE_CHECKING:
    import pytest
    from claude_agent_sdk import ClaudeAgentOptions
    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncSession

GIT_AUTHOR_ARGS = ["-c", "user.email=test@example.com", "-c", "user.name=Test"]


def run_command(*args: str, cwd: Path) -> str:
    result = subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True)
    return result.stdout


def init_bare_origin(tmp_path: Path) -> Path:
    origin = tmp_path / "origin.git"
    run_command("git", "init", "--bare", "--initial-branch=main", str(origin), cwd=tmp_path)
    seed_dir = tmp_path / "seed"
    run_command("git", "clone", str(origin), str(seed_dir), cwd=tmp_path)
    (seed_dir / "README.md").write_text("исходный файл\n")
    run_command("git", "add", "README.md", cwd=seed_dir)
    run_command("git", *GIT_AUTHOR_ARGS, "commit", "-m", "начальный коммит", cwd=seed_dir)
    run_command("git", "push", "origin", "main", cwd=seed_dir)
    return origin


class SharedSession:
    """`async with async_session_factory()` воркера — та же тестовая сессия."""

    def __init__(self, db_session: AsyncSession) -> None:
        self._db_session = db_session

    async def __aenter__(self) -> AsyncSession:
        return self._db_session

    async def __aexit__(self, *_exc_info: object) -> None:
        return None


class KeepOpenRedis:
    """Воркер закрывает свой клиент Redis — тестовый закрывать нельзя."""

    def __init__(self, redis_client: Redis) -> None:
        self._redis_client = redis_client

    def __getattr__(self, name: str) -> Any:
        return getattr(self._redis_client, name)

    async def aclose(self) -> None:
        return None


@dataclass
class WorkerEnv:
    """
    ``client`` — фейк SDK следующего прогона; ``queued_clients`` — фейки,
    которые получат первые созданные клиенты (fork сессии родителя, новый
    процесс при переподключении), раньше ``client``. ``options`` — опции
    каждого созданного клиента по порядку.
    """

    repos_root: Path
    client: FakeClaudeAgentClient = field(
        default_factory=lambda: FakeClaudeAgentClient(messages_per_query=[]),
    )
    queued_clients: list[FakeClaudeAgentClient] = field(default_factory=list)
    options: list[ClaudeAgentOptions] = field(default_factory=list)
    enqueued: list[tuple[Any, Any]] = field(default_factory=list)

    def create_client(self, options: ClaudeAgentOptions) -> FakeClaudeAgentClient:
        self.options.append(options)
        return self.queued_clients.pop(0) if self.queued_clients else self.client


def install_worker_env(
    *,
    db_session: AsyncSession,
    redis_client: Redis,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> WorkerEnv:
    env = WorkerEnv(repos_root=tmp_path / "repos")
    monkeypatch.setenv("TRACKER_REPOS_ROOT", str(env.repos_root))
    monkeypatch.setattr(session_worker, "async_session_factory", lambda: SharedSession(db_session))
    monkeypatch.setattr(
        session_worker,
        "Redis",
        SimpleNamespace(from_url=lambda _url: KeepOpenRedis(redis_client)),
    )
    monkeypatch.setattr(
        session_worker,
        "ClaudeSDKClient",
        lambda options: env.create_client(options),
    )
    monkeypatch.setattr(
        session_worker.run_task_session,
        "apply_async",
        lambda args, kwargs, countdown: env.enqueued.append((args, kwargs)),
    )
    return env
