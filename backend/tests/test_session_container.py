"""
Тесты контейнера сессии (раздел 19.3 ТЗ): обёртка `session_cli.py`, аргументы
`docker run` из `services/session_container.py` и уборка контейнеров без пульса.
"""

from __future__ import annotations

import asyncio
import json
import re
import subprocess
import tomllib
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

import session_cli
from services import docker_mounts, session_container
from services.maintenance_tasks import purge_orphaned_session_containers
from services.session_container import (
    SESSION_CONTAINER_PREFIX,
    SESSION_DOCKER_SPEC_ENV,
    SESSION_TASK_LABEL,
    build_session_cli_env,
)
from services.session_heartbeat import beat

if TYPE_CHECKING:
    from redis.asyncio import Redis

_BACKEND_DIR = Path(__file__).resolve().parent.parent
_SESSION_DOCKERFILE = _BACKEND_DIR.parent / "runners" / "tracker-session" / "Dockerfile"
_WORKER_SECRETS = {
    "SECRET_ENCRYPTION_KEY": "encryption-key-value",
    "SESSION_SECRET_KEY": "session-key-value",
    "DATABASE_URL": "postgresql://tracker:pw@postgres/tracker",
    "REDIS_URL": "redis://:pw@redis:6379/0",
    "VAPID_PRIVATE_KEY": "vapid-key-value",
}


def _spec_env(task_id: uuid.UUID) -> dict[str, str]:
    spec = {
        "name_prefix": f"{SESSION_CONTAINER_PREFIX}{task_id}-",
        "docker_args": ["-w", "/data/repos/RR-1"],
        "image": session_container.DEFAULT_SESSION_IMAGE,
    }
    return {SESSION_DOCKER_SPEC_ENV: json.dumps(spec)}


class TestSessionCli:
    def test_forwards_only_cli_settings_by_name(self) -> None:
        environ = {
            **_WORKER_SECRETS,
            **_spec_env(uuid.uuid4()),
            "CLAUDE_CONFIG_DIR": "/data/claude-accounts/a",
            "ANTHROPIC_BASE_URL": "https://example.com",
            "HTTPS_PROXY": "http://proxy.example.com:3128",
            "PATH": "/usr/bin",
        }

        command = session_cli.build_command([], environ)

        forwarded = [command[i + 1] for i, arg in enumerate(command) if arg == "-e"]
        assert forwarded == ["ANTHROPIC_BASE_URL", "CLAUDE_CONFIG_DIR", "HTTPS_PROXY"]
        assert not any(value in arg for arg in command for value in _WORKER_SECRETS.values())

    def test_cli_arguments_follow_image(self) -> None:
        task_id = uuid.uuid4()
        argv = ["--output-format", "stream-json", "--verbose"]

        command = session_cli.build_command(argv, _spec_env(task_id))

        assert command[:4] == ["docker", "run", "-i", "--rm"]
        assert command[command.index("--name") + 1].startswith(
            f"{SESSION_CONTAINER_PREFIX}{task_id}-"
        )
        image_at = command.index(session_container.DEFAULT_SESSION_IMAGE)
        assert command[image_at + 1 :] == ["claude", *argv]

    def test_without_spec_exits(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(SESSION_DOCKER_SPEC_ENV, raising=False)

        with pytest.raises(SystemExit) as exc_info:
            session_cli.main()

        assert exc_info.value.code != 0


class TestSessionDockerArgs:
    @pytest.fixture(autouse=True)
    def _roots(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TRACKER_REPOS_ROOT", str(tmp_path / "repos"))
        monkeypatch.setenv("TRACKER_USER_FILES_ROOT", str(tmp_path / "files"))
        monkeypatch.setenv("CLAUDE_ACCOUNTS_ROOT", str(tmp_path / "accounts"))

        async def not_in_container(_root: Path) -> None:
            return None

        monkeypatch.setattr(docker_mounts, "resolve_root_mount", not_in_container)

    async def _docker_args(
        self,
        tmp_path: Path,
        *,
        task_id: uuid.UUID,
        config_dir: str,
        with_artifacts: bool,
    ) -> list[str]:
        env = await build_session_cli_env(
            task_id=task_id,
            cwd=tmp_path / "repos" / "RR-1",
            claude_config_dir=config_dir,
            artifacts_dir=tmp_path / "files" / "RR-1" if with_artifacts else None,
        )
        spec = json.loads(env[SESSION_DOCKER_SPEC_ENV])
        args: list[str] = spec["docker_args"]
        return args

    async def test_mounts_only_task_directories(self, tmp_path: Path) -> None:
        task_id = uuid.uuid4()
        config_dir = str(tmp_path / "accounts" / "a")

        args = await self._docker_args(
            tmp_path, task_id=task_id, config_dir=config_dir, with_artifacts=True
        )

        mounts = [args[i + 1] for i, arg in enumerate(args) if arg == "-v"]
        assert mounts == [
            f"{tmp_path}/repos/RR-1:{tmp_path}/repos/RR-1:rw",
            f"{tmp_path}/files/RR-1:{tmp_path}/files/RR-1:rw",
            f"{config_dir}:{config_dir}:rw",
        ]
        assert f"{SESSION_TASK_LABEL}={task_id}" in args
        assert args[args.index("--network") + 1] == "bridge"
        assert args[-2:] == ["-w", f"{tmp_path}/repos/RR-1"]
        assert "--privileged" not in args
        assert not any("docker.sock" in arg for arg in args)

    async def test_parent_fork_without_artifacts(self, tmp_path: Path) -> None:
        args = await self._docker_args(
            tmp_path, task_id=uuid.uuid4(), config_dir="", with_artifacts=False
        )

        assert [args[i + 1] for i, arg in enumerate(args) if arg == "-v"] == [
            f"{tmp_path}/repos/RR-1:{tmp_path}/repos/RR-1:rw",
        ]


def test_session_image_cli_matches_worker_sdk() -> None:
    pyproject = tomllib.loads((_BACKEND_DIR / "pyproject.toml").read_text())
    pinned = next(
        dependency.split("==", 1)[1]
        for dependency in pyproject["project"]["dependencies"]
        if dependency.startswith("claude-agent-sdk==")
    )
    match = re.search(
        r"^ARG CLAUDE_AGENT_SDK_VERSION=(\S+)$", _SESSION_DOCKERFILE.read_text(), re.MULTILINE
    )

    assert match is not None
    assert match.group(1) == pinned


async def _run_session_container(task_id: uuid.UUID) -> str:
    container_name = f"{SESSION_CONTAINER_PREFIX}{task_id}-{uuid.uuid4().hex[:6]}"
    process = await asyncio.create_subprocess_exec(
        "docker",
        "run",
        "-d",
        "--rm",
        "--name",
        container_name,
        "--label",
        f"{SESSION_TASK_LABEL}={task_id}",
        "alpine",
        "sleep",
        "60",
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await process.communicate()
    return container_name


class TestPurgeOrphanedSessionContainers:
    @pytest.mark.parametrize(
        ("alive", "purged"), [(True, False), (False, True)], ids=["alive", "orphaned"]
    )
    async def test_stops_only_without_heartbeat(
        self, redis_client: Redis, alive: bool, purged: bool
    ) -> None:
        task_id = uuid.uuid4()
        if alive:
            await beat(redis_client, task_id)
        container_name = await _run_session_container(task_id)
        try:
            stopped = await purge_orphaned_session_containers(redis_client)
            assert (container_name in stopped) is purged
        finally:
            subprocess.run(["docker", "rm", "-f", container_name], capture_output=True, check=False)
