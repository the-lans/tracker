"""
`deploy/install.sh` (раздел 20.2, 20.4 ТЗ) с заглушками внешних команд.

Настоящие Docker, git и сеть не нужны: `docker`, `git`, `curl`, `sudo` и
пакетный менеджер подменены скриптами, которые пишут свои вызовы в журнал.
Проверяется, что и в каком порядке скрипт просит сделать.
"""

from __future__ import annotations

import gzip
import os
import shutil
import subprocess
import tarfile
from collections.abc import Callable
from pathlib import Path

import pytest

_INSTALL_SCRIPT = Path(__file__).resolve().parents[2] / "deploy" / "install.sh"
# Системные утилиты, которые нужны скрипту и заглушкам. PATH теста состоит
# только из каталога заглушек: настоящий docker (на CI он в /usr/bin) не
# должен быть виден.
_SYSTEM_TOOLS = (
    "bash",
    "sh",
    "cat",
    "cp",
    "rm",
    "chmod",
    "mktemp",
    "find",
    "sort",
    "tail",
    "gzip",
    "basename",
    "id",
    "sed",
    "grep",
    "openssl",
)

_DOCKER_STUB = """#!/bin/sh
echo "docker $*" >> "$STUB_LOG"
if [ "$1 $2" = "compose version" ] && [ -f "$STUB_DIR/no-compose" ]; then
  exit 1
fi
if [ "$1 $2 $3" = "compose exec -T" ]; then
  cat > "$STUB_DIR/psql-input"
fi
case "$*" in
  *seed_periodic_tasks*) [ -f "$STUB_DIR/fail-seed" ] && exit 1 ;;
esac
if [ "$1" = "version" ]; then
  cat "$STUB_DIR/engine-version" 2>/dev/null || echo "27.3.1"
fi
exit 0
"""
_LOGGING_STUB = """#!/bin/sh
echo "{name} $*" >> "$STUB_LOG"
"""
# «Официальный установщик»: ставит docker в PATH, как это сделал бы get.docker.com.
_CURL_STUB = """#!/bin/sh
echo "curl $*" >> "$STUB_LOG"
while [ "$#" -gt 0 ]; do
  if [ "$1" = "-o" ]; then
    printf 'cp "$STUB_DIR/docker.real" "$STUB_DIR/docker"\\nchmod +x "$STUB_DIR/docker"\\n' > "$2"
  fi
  shift
done
"""
_SUDO_STUB = """#!/bin/sh
exec "$@"
"""
_APT_STUB = """#!/bin/sh
echo "apt-get $*" >> "$STUB_LOG"
rm -f "$STUB_DIR/no-compose"
"""


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content)
    path.chmod(0o755)


@pytest.fixture
def stubs(tmp_path: Path) -> Path:
    stub_dir = tmp_path / "stubs"
    stub_dir.mkdir()
    for tool in _SYSTEM_TOOLS:
        tool_path = shutil.which(tool)
        assert tool_path is not None, f"нет системной утилиты {tool}"
        (stub_dir / tool).symlink_to(tool_path)
    _write_executable(stub_dir / "docker", _DOCKER_STUB)
    (stub_dir / "docker.real").write_text(_DOCKER_STUB)
    _write_executable(stub_dir / "git", _LOGGING_STUB.format(name="git"))
    _write_executable(stub_dir / "curl", _CURL_STUB)
    _write_executable(stub_dir / "sudo", _SUDO_STUB)
    _write_executable(stub_dir / "apt-get", _APT_STUB)
    return stub_dir


@pytest.fixture
def install_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "opt-tracker"
    (directory / ".git").mkdir(parents=True)
    return directory


def _run_bash(
    script: str,
    *args: str,
    stubs: Path,
    install_dir: Path,
) -> subprocess.CompletedProcess[str]:
    env = {
        "PATH": str(stubs),
        "HOME": str(install_dir.parent),
        "INSTALL_DIR": str(install_dir),
        "STUB_DIR": str(stubs),
        "STUB_LOG": str(stubs / "calls.log"),
    }
    return subprocess.run(
        [str(stubs / "bash"), "-c", script, "install.sh", *args],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def _calls(stubs: Path) -> list[str]:
    log = stubs / "calls.log"
    return log.read_text().splitlines() if log.exists() else []


def _make_restore_dir(tmp_path: Path, *, skip: str | None = None) -> Path:
    restore_dir = tmp_path / "transfer"
    restore_dir.mkdir()
    files: dict[str, Callable[[Path], object]] = {
        ".env": lambda path: path.write_text("SECRET_ENCRYPTION_KEY=старый-ключ\n"),
        "tracker-20261001T000000Z.sql.gz": lambda path: path.write_bytes(
            gzip.compress(b"-- old dump\n"),
        ),
        "tracker-20261019T000000Z.sql.gz": lambda path: path.write_bytes(
            gzip.compress(b"-- fresh dump\n"),
        ),
    }
    for name, write in files.items():
        if name != skip:
            write(restore_dir / name)
    for archive in (
        "task_repos.tar.gz",
        "user_files.tar.gz",
        "log_archive.tar.gz",
        "claude_accounts.tar.gz",
        "sftp_host_keys.tar.gz",
    ):
        if archive != skip:
            with tarfile.open(restore_dir / archive, "w:gz"):
                pass
    return restore_dir


class TestScriptSyntax:
    def test_valid(self) -> None:
        subprocess.run(["bash", "-n", str(_INSTALL_SCRIPT)], check=True)


class TestRestore:
    def test_steps_in_order(
        self,
        tmp_path: Path,
        stubs: Path,
        install_dir: Path,
    ) -> None:
        restore_dir = _make_restore_dir(tmp_path)

        result = _run_bash(
            f'exec bash "{_INSTALL_SCRIPT}" "$@"',
            "--restore",
            str(restore_dir),
            stubs=stubs,
            install_dir=install_dir,
        )

        assert result.returncode == 0, result.stdout + result.stderr
        docker_calls = [call for call in _calls(stubs) if call.startswith("docker")]
        expected_order = [
            "docker compose build backend frontend",
            "docker compose up -d --wait postgres redis",
            "docker compose exec -T postgres",
            "task_repos.tar.gz",
            "user_files.tar.gz",
            "log_archive.tar.gz",
            "claude_accounts.tar.gz",
            "sftp_host_keys.tar.gz",
            "docker compose run --rm backend alembic upgrade head",
            "docker compose up -d backend worker session-worker beat sftp frontend caddy backup",
        ]
        positions = [
            next(index for index, call in enumerate(docker_calls) if expected in call)
            for expected in expected_order
        ]
        assert positions == sorted(positions)
        assert not any("seed_" in call for call in docker_calls)
        assert (stubs / "psql-input").read_text() == "-- fresh dump\n"
        # Ключи старого сервера сохранены; пароль роли шлюза .env прежней
        # версии не знал — он дописан.
        env_lines = (install_dir / ".env").read_text().splitlines()
        assert env_lines[0] == "SECRET_ENCRYPTION_KEY=старый-ключ"
        assert env_lines[1].startswith("SFTP_DB_PASSWORD=")
        assert len(env_lines[1].removeprefix("SFTP_DB_PASSWORD=")) == 48
        # У backend volume ключа хоста только для чтения — распаковывает шлюз.
        [host_keys_call] = [call for call in docker_calls if "sftp_host_keys.tar.gz" in call]
        assert "--entrypoint sh sftp" in host_keys_call

    @pytest.mark.parametrize(
        "missing",
        [".env", "user_files.tar.gz", "log_archive.tar.gz"],
    )
    def test_incomplete_transfer(
        self,
        tmp_path: Path,
        stubs: Path,
        install_dir: Path,
        missing: str,
    ) -> None:
        restore_dir = _make_restore_dir(tmp_path, skip=missing)

        result = _run_bash(
            f'exec bash "{_INSTALL_SCRIPT}" "$@"',
            "--restore",
            str(restore_dir),
            stubs=stubs,
            install_dir=install_dir,
        )

        assert result.returncode != 0
        assert missing in result.stdout
        assert _calls(stubs) == []

    def test_without_claude_accounts(
        self,
        tmp_path: Path,
        stubs: Path,
        install_dir: Path,
    ) -> None:
        """Перенос с сервера прежней версии: volume `claude_accounts` там ещё не было."""
        restore_dir = _make_restore_dir(tmp_path, skip="claude_accounts.tar.gz")

        result = _run_bash(
            f'exec bash "{_INSTALL_SCRIPT}" "$@"',
            "--restore",
            str(restore_dir),
            stubs=stubs,
            install_dir=install_dir,
        )

        assert result.returncode == 0, result.stdout + result.stderr
        assert "claude_accounts.tar.gz нет в переносе" in result.stdout
        docker_calls = [call for call in _calls(stubs) if call.startswith("docker")]
        assert any("log_archive.tar.gz" in call for call in docker_calls)
        assert not any("claude_accounts.tar.gz" in call for call in docker_calls)

    def test_unknown_argument(self, stubs: Path, install_dir: Path) -> None:
        result = _run_bash(
            f'exec bash "{_INSTALL_SCRIPT}" "$@"',
            "--bogus",
            stubs=stubs,
            install_dir=install_dir,
        )

        assert result.returncode == 2


class TestUpdate:
    """Раздел 20.6: обновление пересобирает все образы, в том числе вне compose."""

    def test_steps_in_order(self, stubs: Path, install_dir: Path) -> None:
        (install_dir / ".env").write_text("SECRET_ENCRYPTION_KEY=ключ\nSFTP_DB_PASSWORD=пароль\n")

        result = _run_bash(
            f'exec bash "{_INSTALL_SCRIPT}" "$@"',
            "--update",
            stubs=stubs,
            install_dir=install_dir,
        )

        assert result.returncode == 0, result.stdout + result.stderr
        calls = _calls(stubs)
        expected_order = [
            "pull --ff-only",
            "docker compose build backend frontend",
            "docker build -t tracker-runner-python:latest",
            "docker build -t tracker-runner-bash:latest",
            "docker build -t tracker-session:latest",
            "docker compose up -d --wait postgres redis",
            "alembic upgrade head",
            "seed_periodic_tasks.py",
            "docker compose up -d backend worker session-worker beat sftp frontend caddy backup",
        ]
        positions = [
            next(index for index, call in enumerate(calls) if expected in call)
            for expected in expected_order
        ]
        assert positions == sorted(positions)
        assert not any("seed_admin_allowlist" in call or "git clone" in call for call in calls)
        assert (install_dir / ".env").read_text().count("SFTP_DB_PASSWORD=") == 1

    def test_requires_installation(self, stubs: Path, install_dir: Path) -> None:
        result = _run_bash(
            f'exec bash "{_INSTALL_SCRIPT}" "$@"',
            "--update",
            stubs=stubs,
            install_dir=install_dir,
        )

        assert result.returncode != 0
        assert not any(call.startswith("docker") for call in _calls(stubs))

    def test_not_with_restore(self, tmp_path: Path, stubs: Path, install_dir: Path) -> None:
        result = _run_bash(
            f'exec bash "{_INSTALL_SCRIPT}" "$@"',
            "--update",
            "--restore",
            str(_make_restore_dir(tmp_path)),
            stubs=stubs,
            install_dir=install_dir,
        )

        assert result.returncode == 2


class TestEnsureEnvValue:
    """Перенос со старого сервера: новые переменные дописываются, заданные — не трогаются."""

    @pytest.mark.parametrize(
        ("content", "expected"),
        [
            ("SFTP_DB_PASSWORD=old\n", "SFTP_DB_PASSWORD=old\n"),
            ("SFTP_DB_PASSWORD=\n", "SFTP_DB_PASSWORD=new\n"),
            ("OTHER=1\n", "OTHER=1\nSFTP_DB_PASSWORD=new\n"),
        ],
        ids=["kept", "empty_filled", "appended"],
    )
    def test_value(
        self,
        stubs: Path,
        install_dir: Path,
        content: str,
        expected: str,
    ) -> None:
        env_file = install_dir / ".env"
        env_file.write_text(content)

        result = _run_bash(
            f'source "{_INSTALL_SCRIPT}" && _ensure_env_value SFTP_DB_PASSWORD new',
            stubs=stubs,
            install_dir=install_dir,
        )

        assert result.returncode == 0, result.stdout + result.stderr
        assert env_file.read_text() == expected


class TestInstallDocker:
    def test_installs_engine_when_missing(self, stubs: Path, install_dir: Path) -> None:
        (stubs / "docker").unlink()

        result = _run_bash(
            f'source "{_INSTALL_SCRIPT}" && step_install_docker',
            stubs=stubs,
            install_dir=install_dir,
        )

        assert result.returncode == 0, result.stdout + result.stderr
        assert "curl -fsSL https://get.docker.com" in _calls(stubs)[0]
        assert os.access(stubs / "docker", os.X_OK)

    def test_installs_compose_plugin(self, stubs: Path, install_dir: Path) -> None:
        (stubs / "no-compose").touch()

        result = _run_bash(
            f'source "{_INSTALL_SCRIPT}" && step_install_docker',
            stubs=stubs,
            install_dir=install_dir,
        )

        assert result.returncode == 0, result.stdout + result.stderr
        assert "apt-get install -y docker-compose-plugin" in _calls(stubs)


class TestDockerEngineVersion:
    """Раздел 20.2 п. 1: `volume-subpath` script-нод требует Docker Engine 26+."""

    @pytest.mark.parametrize(
        ("version", "ok"),
        [("26.0.0", True), ("29.5.2", True), ("25.0.5", False), ("garbage", False)],
        ids=["min", "new", "old", "unparsable"],
    )
    def test_check(self, stubs: Path, install_dir: Path, version: str, ok: bool) -> None:
        (stubs / "engine-version").write_text(f"{version}\n")

        result = _run_bash(
            f'source "{_INSTALL_SCRIPT}" && step_install_docker',
            stubs=stubs,
            install_dir=install_dir,
        )

        assert (result.returncode == 0) is ok, result.stdout + result.stderr
        if not ok:
            assert "Docker Engine" in result.stdout + result.stderr


class TestSeedData:
    """Раздел 20.2 п. 8: начальные данные — до первого входа администратора."""

    def _run(self, stubs: Path, install_dir: Path) -> subprocess.CompletedProcess[str]:
        return _run_bash(
            f'source "{_INSTALL_SCRIPT}" && ADMIN_EMAIL=admin@example.com step_seed_data',
            stubs=stubs,
            install_dir=install_dir,
        )

    def test_seeds_both(self, stubs: Path, install_dir: Path) -> None:
        result = self._run(stubs, install_dir)

        assert result.returncode == 0, result.stdout + result.stderr
        calls = _calls(stubs)
        assert any("seed_admin_allowlist.py admin@example.com" in call for call in calls)
        assert any("seed_periodic_tasks.py" in call for call in calls)
        assert "после первого входа" not in result.stdout

    def test_periodic_seed_failure_stops_install(self, stubs: Path, install_dir: Path) -> None:
        (stubs / "fail-seed").touch()

        result = self._run(stubs, install_dir)

        assert result.returncode != 0
