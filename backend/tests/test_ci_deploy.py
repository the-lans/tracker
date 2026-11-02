"""
`deploy/ci_deploy.sh` (раздел 20.7 ТЗ): принудительная команда ключа
развёртывания пропускает только `deploy <sha> [--force | --wait-idle N]`
и `previous-ref`. Вместо `install.sh` — заглушка, записывающая аргументы.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CI_DEPLOY = _REPO_ROOT / "deploy" / "ci_deploy.sh"
_VERIFY_SCRIPT = _REPO_ROOT / ".github" / "scripts" / "verify_deployment.sh"
_SHA = "0123456789abcdef0123456789abcdef01234567"
_INSTALL_STUB = """#!/bin/sh
echo "$INSTALL_DIR $*" > "$(dirname "$0")/install-args"
exit "${STUB_EXIT:-0}"
"""


@pytest.fixture
def install_dir(tmp_path: Path) -> Path:
    deploy_dir = tmp_path / "opt-tracker" / "deploy"
    deploy_dir.mkdir(parents=True)
    shutil.copy2(_CI_DEPLOY, deploy_dir / "ci_deploy.sh")
    stub = deploy_dir / "install.sh"
    stub.write_text(_INSTALL_STUB)
    stub.chmod(0o755)
    return deploy_dir.parent


def _run(
    install_dir: Path,
    command: str | None,
    *,
    stub_exit: int = 0,
) -> subprocess.CompletedProcess[str]:
    env = {"PATH": "/usr/bin:/bin", "STUB_EXIT": str(stub_exit)}
    if command is not None:
        env["SSH_ORIGINAL_COMMAND"] = command
    return subprocess.run(
        ["bash", str(install_dir / "deploy" / "ci_deploy.sh")],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def _install_args(install_dir: Path) -> str | None:
    args = install_dir / "deploy" / "install-args"
    return args.read_text().strip() if args.exists() else None


class TestDeploy:
    @pytest.mark.parametrize(
        ("flags", "expected"),
        [
            ("", f"--update --ref {_SHA} --wait-idle 60"),
            (" --force", f"--update --ref {_SHA}"),
            (" --wait-idle 15", f"--update --ref {_SHA} --wait-idle 15"),
        ],
        ids=["default_wait", "force", "wait"],
    )
    def test_runs_update(self, install_dir: Path, flags: str, expected: str) -> None:
        result = _run(install_dir, f"deploy {_SHA}{flags}")

        assert result.returncode == 0, result.stderr
        assert _install_args(install_dir) == f"{install_dir} {expected}"

    def test_exit_code_passed_through(self, install_dir: Path) -> None:
        assert _run(install_dir, f"deploy {_SHA}", stub_exit=3).returncode == 3

    @pytest.mark.parametrize(
        "command",
        [
            None,
            "",
            "deploy",
            "deploy abc1234",
            f"deploy {_SHA.upper()}",
            f"deploy {_SHA}; reboot",
            f"deploy {_SHA} --force --force",
            f"deploy {_SHA} --wait-idle",
            f"deploy {_SHA} --wait-idle 0",
            f"deploy {_SHA} --wait-idle 1441",
            f"deploy {_SHA} --wait-idle 5m",
            f"deploy {_SHA}\nreboot",
            f"deploy $(reboot) {_SHA}",
            "bash -i",
            "previous-ref now",
        ],
        ids=[
            "no_command",
            "empty",
            "no_sha",
            "short_sha",
            "uppercase_sha",
            "chained",
            "repeated_flag",
            "wait_without_minutes",
            "zero_minutes",
            "too_long",
            "minutes_unit",
            "newline",
            "substitution",
            "shell",
            "previous_ref_args",
        ],
    )
    def test_rejected(self, install_dir: Path, command: str | None) -> None:
        result = _run(install_dir, command)

        assert result.returncode == 2
        assert _install_args(install_dir) is None


class TestPreviousRef:
    def test_printed(self, install_dir: Path) -> None:
        state = install_dir / ".deploy"
        state.mkdir()
        (state / "previous_ref").write_text(f"{_SHA}\n")

        result = _run(install_dir, "previous-ref")

        assert (result.returncode, result.stdout.strip()) == (0, _SHA)

    def test_missing(self, install_dir: Path) -> None:
        result = _run(install_dir, "previous-ref")

        assert (result.returncode, result.stdout) == (1, "")


# python3 нужен скрипту проверки для разбора JSON ответа.
_PYTHON_DIR = Path(shutil.which("python3") or "/usr/bin/python3").parent
# Отвечает содержимым файла по последнему сегменту адреса; нет файла — ошибка HTTP.
_CURL_STUB = """#!/bin/sh
for last; do :; done
case "$last" in
  */api/health) file="$STUB_DIR/health" ;;
  */) file="$STUB_DIR/index" ;;
esac
[ -f "$file" ] || exit 22
cat "$file"
"""


class TestVerifyDeployment:
    """Проверка после развёртывания: SHA в /api/health и index.html фронтенда."""

    @pytest.fixture
    def stub_dir(self, tmp_path: Path) -> Path:
        stub = tmp_path / "curl"
        stub.write_text(_CURL_STUB)
        stub.chmod(0o755)
        (tmp_path / "index").write_text('<body><div id="root"></div></body>')
        return tmp_path

    def _verify(self, stub_dir: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", str(_VERIFY_SCRIPT), _SHA],
            capture_output=True,
            text=True,
            env={
                "PATH": f"{stub_dir}:{_PYTHON_DIR}:/usr/bin:/bin",
                "STUB_DIR": str(stub_dir),
                "DEPLOY_DOMAIN": "tracker.example.com",
                "HEALTH_TIMEOUT_SECONDS": "0",
                "HEALTH_POLL_SECONDS": "0",
            },
            check=False,
        )

    def test_deployed(self, stub_dir: Path) -> None:
        (stub_dir / "health").write_text(f'{{"status": "ok", "version": "{_SHA}"}}')

        result = self._verify(stub_dir)

        assert result.returncode == 0, result.stdout + result.stderr

    @pytest.mark.parametrize(
        ("health", "index"),
        [
            ('{"status": "ok", "version": "unknown"}', True),
            (None, True),
            (f'{{"status": "ok", "version": "{_SHA}"}}', False),
        ],
        ids=["old_version", "health_down", "no_frontend"],
    )
    def test_not_deployed(self, stub_dir: Path, health: str | None, index: bool) -> None:
        if health is not None:
            (stub_dir / "health").write_text(health)
        if not index:
            (stub_dir / "index").unlink()

        result = self._verify(stub_dir)

        assert result.returncode == 1
        assert _SHA in result.stdout
