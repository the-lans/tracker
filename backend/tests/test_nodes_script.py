"""Тесты `services/nodes/script.py` — реальные Docker-контейнеры, не моки
(раздел 21.1: "изоляция выполнения script-нод" — единственный способ
действительно проверить `--network none` и лимиты ресурсов).

Требует собранные локально образы ``tracker-runner-python:latest`` и
``tracker-runner-bash:latest`` (см. ``runners/*/Dockerfile``):
``docker build -t tracker-runner-python:latest runners/tracker-runner-python/``
(аналогично для bash).
"""

from __future__ import annotations

from pathlib import Path

from db.models.enums import ScriptLanguage
from services.nodes.script import run_script_node

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
