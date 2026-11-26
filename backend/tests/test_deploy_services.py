"""Проверки развёртывания до переключения кода и после запуска сервисов."""

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "deploy" / "install.sh"


def run_shell(body: str, **env: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "-c", f'source "$SCRIPT"\n{body}'],
        env={**os.environ, "SCRIPT": str(SCRIPT), "INSTALL_DIR": str(ROOT), **env},
        text=True,
        capture_output=True,
        check=False,
    )


@pytest.mark.parametrize(
    "revision, expected",
    [("e4ac0721df52", 0), ("f4c2a8e6b913", 0), ("unknown_revision", 3)],
)
def test_revision_checked_before_checkout(revision: str, expected: int) -> None:
    result = run_shell(
        'docker() { printf "%s\\n" "$REVISION"; }\n_check_database_revision HEAD',
        REVISION=revision,
    )
    assert result.returncode == expected, result.stdout + result.stderr


def test_all_services_checked() -> None:
    result = run_shell(
        """docker() {
          if [ "$1" = inspect ]; then echo running; else echo "$4"; fi
        }
        step_verify_app_services"""
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_failed_service_is_reported(tmp_path: Path) -> None:
    clock = tmp_path / "clock"
    clock.write_text("0")
    result = run_shell(
        """docker() {
          if [ "$1" = inspect ]; then echo exited; else echo container; fi
        }
        date() { n=$(cat "$CLOCK"); n=$((n + 100)); echo "$n" > "$CLOCK"; echo "$n"; }
        sleep() { :; }
        step_verify_app_services""",
        CLOCK=str(clock),
    )
    assert result.returncode == 1
    assert "llm-gateway" in result.stdout
