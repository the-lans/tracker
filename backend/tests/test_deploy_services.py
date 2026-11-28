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


@pytest.mark.parametrize("service", ["worker", "session-worker", "test-worker", "backup-worker"])
def test_celery_worker_must_respond(service: str, tmp_path: Path) -> None:
    clock = tmp_path / "clock"
    clock.write_text("0")
    result = run_shell(
        """docker() {
          case "$*" in
            *Config.Hostname*) echo container-host ;;
            "inspect "*) echo running ;;
            "compose exec -T $FAILED "*) return 1 ;;
            "compose exec -T "*) return 0 ;;
            *) echo container ;;
          esac
        }
        date() { n=$(cat "$CLOCK"); n=$((n + 100)); echo "$n" > "$CLOCK"; echo "$n"; }
        sleep() { :; }
        step_verify_app_services""",
        CLOCK=str(clock),
        FAILED=service,
    )
    assert result.returncode == 1
    assert f"воркер {service} не ответил" in result.stdout


def test_celery_checks_target_each_container(tmp_path: Path) -> None:
    calls = tmp_path / "calls"
    result = run_shell(
        """docker() {
          case "$*" in
            *Config.Hostname*) echo container-host ;;
            "inspect "*) echo running ;;
            "compose exec -T "*) echo "$*" >> "$CALLS" ;;
            *) echo container ;;
          esac
        }
        sleep() { :; }
        step_verify_app_services""",
        CALLS=str(calls),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    commands = calls.read_text().splitlines()
    assert len(commands) == 4
    for service, command in zip(
        ("worker", "session-worker", "test-worker", "backup-worker"), commands, strict=True
    ):
        assert f"exec -T {service} " in command
        assert "--destination celery@container-host" in command
