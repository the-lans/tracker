"""
Общая обвязка тестов воркера сессии — не файл с тестами (как `fakes.py`).

Реальный `ClaudeSDKClient` подменяется фейком, собственные сессии БД и
Redis воркера — тестовыми (в общей откатываемой транзакции). Origin
репозитория — локальный bare-репозиторий, как в `test_git_ops.py`.
"""

from __future__ import annotations

import json
import subprocess
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from services.session_container import (
    SESSION_CLI_PATH,
    SESSION_DOCKER_SPEC_ENV,
    SESSION_TASK_LABEL,
)
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


def assert_cli_in_session_container(options: ClaudeAgentOptions, task_id: uuid.UUID) -> None:
    """
    Раздел 19.3: CLI запускается обёрткой `session_cli.py` в контейнере
    сессии с меткой задачи, а не в контейнере воркера.
    """
    assert options.cli_path == str(SESSION_CLI_PATH)
    spec = json.loads(options.env[SESSION_DOCKER_SPEC_ENV])
    assert f"{SESSION_TASK_LABEL}={task_id}" in spec["docker_args"]


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
    # Каталоги LLM-аккаунтов тестовых задач — во временной директории теста.
    monkeypatch.setattr("tests.factories.DEFAULT_ACCOUNTS_ROOT", str(tmp_path / "accounts"))
    monkeypatch.setattr(session_worker, "async_session_factory", lambda: SharedSession(db_session))

    @asynccontextmanager
    async def shared_redis() -> AsyncIterator[Redis]:
        # Общий клиент теста: воркер получает его вместо нового подключения.
        yield redis_client

    monkeypatch.setattr(session_worker, "redis_connection", shared_redis)
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
