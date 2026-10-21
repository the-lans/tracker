"""Тесты `services/nodes/script.py` — реальные Docker-контейнеры, не моки
(раздел 21.1: "изоляция выполнения script-нод" — единственный способ
действительно проверить `--network none` и лимиты ресурсов).

Требует собранные локально образы ``tracker-runner-python:latest`` и
``tracker-runner-bash:latest`` (см. ``runners/*/Dockerfile``):
``docker build -t tracker-runner-python:latest runners/tracker-runner-python/``
(аналогично для bash).
"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest

from db.models.enums import ScriptLanguage
from services.nodes import script as script_module
from services.nodes.script import (
    RepositoryMountError,
    RootMount,
    parse_root_mount,
    repos_mount_args,
    resolve_root_mount,
    run_script_node,
)

_GENEROUS_TIMEOUT_SECONDS = 30


async def test_python_script_runs_and_captures_stdout(tmp_path: Path) -> None:
    result = await run_script_node(
        script_content="print('привет из контейнера')",
        script_language=ScriptLanguage.PYTHON,
        docker_image=None,
        repos_path=tmp_path,
        timeout_seconds=_GENEROUS_TIMEOUT_SECONDS,
    )

    assert result.exit_code == 0
    assert "привет из контейнера" in result.stdout
    assert result.timed_out is False


async def test_bash_script_runs_and_captures_stdout(tmp_path: Path) -> None:
    result = await run_script_node(
        script_content="echo из bash-раннера",
        script_language=ScriptLanguage.BASH,
        docker_image=None,
        repos_path=tmp_path,
        timeout_seconds=_GENEROUS_TIMEOUT_SECONDS,
    )

    assert result.exit_code == 0
    assert "из bash-раннера" in result.stdout


async def test_script_exit_code_is_propagated(tmp_path: Path) -> None:
    result = await run_script_node(
        script_content="import sys; sys.exit(7)",
        script_language=ScriptLanguage.PYTHON,
        docker_image=None,
        repos_path=tmp_path,
        timeout_seconds=_GENEROUS_TIMEOUT_SECONDS,
    )

    assert result.exit_code == 7


async def test_script_has_no_network_access(tmp_path: Path) -> None:
    # Раздел 19.3: "Контейнер скрипт-ноды не должен иметь доступа к сети
    # без исключений" — попытка сетевого вызова обязана провалиться.
    script = (
        "import socket\n"
        "s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)\n"
        "s.settimeout(3)\n"
        "s.connect(('8.8.8.8', 53))\n"
    )

    result = await run_script_node(
        script_content=script,
        script_language=ScriptLanguage.PYTHON,
        docker_image=None,
        repos_path=tmp_path,
        timeout_seconds=_GENEROUS_TIMEOUT_SECONDS,
    )

    assert result.exit_code != 0


async def test_script_can_read_and_write_mounted_repos_path(tmp_path: Path) -> None:
    (tmp_path / "existing.txt").write_text("уже здесь\n")
    script = (
        f"with open('{tmp_path}/existing.txt') as f:\n"
        "    content = f.read()\n"
        f"with open('{tmp_path}/written_by_script.txt', 'w') as f:\n"
        "    f.write(content)\n"
    )

    result = await run_script_node(
        script_content=script,
        script_language=ScriptLanguage.PYTHON,
        docker_image=None,
        repos_path=tmp_path,
        timeout_seconds=_GENEROUS_TIMEOUT_SECONDS,
    )

    assert result.exit_code == 0
    assert (tmp_path / "written_by_script.txt").read_text() == "уже здесь\n"


async def test_script_exceeding_timeout_is_marked_timed_out(tmp_path: Path) -> None:
    result = await run_script_node(
        script_content="import time; time.sleep(10)",
        script_language=ScriptLanguage.PYTHON,
        docker_image=None,
        repos_path=tmp_path,
        timeout_seconds=1,
    )

    assert result.timed_out is True


async def test_temporary_script_file_is_cleaned_up(tmp_path: Path) -> None:
    await run_script_node(
        script_content="print('ok')",
        script_language=ScriptLanguage.PYTHON,
        docker_image=None,
        repos_path=tmp_path,
        timeout_seconds=_GENEROUS_TIMEOUT_SECONDS,
    )

    scripts_dir = tmp_path / ".tracker-scripts"
    assert list(scripts_dir.iterdir()) == []


async def test_cancelled_script_stops_its_container(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Кнопка «Остановить» отменяет корутину ноды — контейнер не должен жить дальше."""
    stopped: list[str] = []
    original_stop = script_module._force_stop_container

    async def spy_stop(container_name: str) -> None:
        stopped.append(container_name)
        await original_stop(container_name)

    monkeypatch.setattr(script_module, "_force_stop_container", spy_stop)
    run = asyncio.ensure_future(
        run_script_node(
            script_content="import time\ntime.sleep(60)\n",
            script_language=ScriptLanguage.PYTHON,
            docker_image=None,
            repos_path=tmp_path,
            timeout_seconds=120,
        ),
    )
    await asyncio.sleep(2)

    run.cancel()
    with pytest.raises(asyncio.CancelledError):
        await run

    assert len(stopped) == 1
    running = subprocess.run(
        ["docker", "ps", "-q", "--filter", f"name={stopped[0]}"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert running.stdout.strip() == ""


class TestEnv:
    async def test_script_sees_task_variables(self, tmp_path: Path) -> None:
        result = await run_script_node(
            script_content=(
                "import os\n"
                "print(os.environ['API_URL'])\n"
                "print(os.environ['MULTILINE'].splitlines()[1])\n"
            ),
            script_language=ScriptLanguage.PYTHON,
            docker_image=None,
            repos_path=tmp_path,
            timeout_seconds=_GENEROUS_TIMEOUT_SECONDS,
            env={"API_URL": "https://api.example.com", "MULTILINE": "раз\nдва"},
        )

        assert result.exit_code == 0, result.stderr
        assert result.stdout.splitlines() == ["https://api.example.com", "два"]


class TestReposMount:
    """Раздел 11.4, 19.3: монтируется только директория задачи."""

    def test_outside_container(self, tmp_path: Path) -> None:
        assert repos_mount_args(tmp_path, None) == ["-v", f"{tmp_path}:{tmp_path}:rw"]

    def test_volume_subpath(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TRACKER_REPOS_ROOT", str(tmp_path))
        repos_path = tmp_path / "RR-10001"
        mount = RootMount(type="volume", name="ai-tracker_task_repos", source="/var/lib/docker/x")

        assert repos_mount_args(repos_path, mount) == [
            "--mount",
            f"type=volume,src=ai-tracker_task_repos,dst={repos_path},volume-subpath=RR-10001",
        ]

    def test_host_directory(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TRACKER_REPOS_ROOT", str(tmp_path))
        repos_path = tmp_path / "RR-10001"
        mount = RootMount(type="bind", name="", source="/srv/tracker data/repos")

        assert repos_mount_args(repos_path, mount) == [
            "-v",
            f"/srv/tracker data/repos/RR-10001:{repos_path}:rw",
        ]

    @pytest.mark.parametrize("relative", ["..", "."], ids=["outside_root", "root_itself"])
    def test_rejects_path(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        relative: str,
    ) -> None:
        monkeypatch.setenv("TRACKER_REPOS_ROOT", str(tmp_path / "repos"))
        mount = RootMount(type="volume", name="v", source="/x")

        with pytest.raises(ValueError, match="корн"):
            repos_mount_args(tmp_path / "repos" / relative, mount)


class TestParseRootMount:
    @pytest.mark.parametrize(
        ("line", "expected"),
        [
            (
                "volume ai-tracker_task_repos /var/lib/docker/volumes/x\n",
                RootMount("volume", "ai-tracker_task_repos", "/var/lib/docker/volumes/x"),
            ),
            ("bind  /srv/tracker data/repos\n", RootMount("bind", "", "/srv/tracker data/repos")),
            ("\n", None),
        ],
        ids=["volume", "bind_with_space", "not_mounted"],
    )
    def test_parse(self, line: str, expected: RootMount | None) -> None:
        assert parse_root_mount(line) == expected


class TestResolveRootMount:
    """Неудачная проверка не кешируется; в контейнере — ошибка, а не путь хоста."""

    @pytest.fixture(autouse=True)
    def _clean_cache(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(script_module, "_root_mount_cache", {})

    def _inspect_results(
        self,
        monkeypatch: pytest.MonkeyPatch,
        results: list[RootMount | None],
    ) -> list[int]:
        calls: list[int] = []

        async def fake_inspect() -> RootMount | None:
            calls.append(1)
            return results[len(calls) - 1]

        monkeypatch.setattr(script_module, "_inspect_root_mount", fake_inspect)
        return calls

    async def test_retry_after_failure(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        marker = tmp_path / ".dockerenv"
        marker.touch()
        monkeypatch.setattr(script_module, "_CONTAINER_MARKER", marker)
        mount = RootMount(type="volume", name="v", source="/x")
        calls = self._inspect_results(monkeypatch, [None, mount, None])

        with pytest.raises(RepositoryMountError):
            await resolve_root_mount()
        assert await resolve_root_mount() == mount
        assert await resolve_root_mount() == mount
        assert len(calls) == 2

    async def test_outside_container(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(script_module, "_CONTAINER_MARKER", tmp_path / "absent")
        self._inspect_results(monkeypatch, [None])

        assert await resolve_root_mount() is None
