"""
`deploy/install.sh` (раздел 20.2, 20.4 ТЗ) с заглушками внешних команд.

Настоящие Docker, git и сеть не нужны: `docker`, `git`, `curl`, `sudo` и
пакетный менеджер подменены скриптами, которые пишут свои вызовы в журнал.
Проверяется, что и в каком порядке скрипт просит сделать.
"""

from __future__ import annotations

import gzip
import os
import re
import shutil
import subprocess
import tarfile
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa

from db.models.enums import TaskStatus
from services.backup.bundle import AFTER_RESTORE_SQL_NAME
from services.backup.components import COMPONENTS
from services.backup.verify import SFTP_DB_ROLE_SQL
from services.maintenance import MAINTENANCE_KEY
from services.periodic_tasks import NIGHT_DISPATCH_TASK
from services.task_status import SESSION_ACTIVE_STATUSES
from tasks.celery_app import DISPATCH_READY_TASKS
from tasks.periodic import measure_volume_usage

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


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
    "mkdir",
    "date",
    "sleep",
    "head",
    "wc",
)
_PREVIOUS_SHA = "1" * 40
_TARGET_SHA = "2" * 40
_REDIS_PASSWORD = "redis-pass-from-env"

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
  *"UPDATE tasks SET status"*) [ -f "$STUB_DIR/fail-reset" ] && exit 1 ;;
esac
if [ "$1" = "version" ]; then
  cat "$STUB_DIR/engine-version" 2>/dev/null || echo "27.3.1"
fi
case "$*" in
  *"redis-cli SET"*) echo "OK" ;;
  *psql*)
    # Число живых сессий: по строке файла на опрос, последняя повторяется.
    if [ -s "$STUB_DIR/live-sessions" ]; then
      head -n 1 "$STUB_DIR/live-sessions"
      if [ "$(wc -l < "$STUB_DIR/live-sessions")" -gt 1 ]; then
        sed -i.bak 1d "$STUB_DIR/live-sessions"
      fi
    else
      echo 0
    fi
    ;;
esac
exit 0
"""
# Ведёт себя как git в установленном репозитории: HEAD, переход на коммит,
# проверка, что коммит входит в историю origin/main.
_GIT_STUB = f"""#!/bin/sh
echo "git $*" >> "$STUB_LOG"
case "$*" in
  *"rev-parse --verify"*) echo "{_TARGET_SHA}" ;;
  *"rev-parse HEAD"*) cat "$STUB_DIR/git-head" 2>/dev/null || echo "{_PREVIOUS_SHA}" ;;
  *"merge-base --is-ancestor"*) [ -f "$STUB_DIR/not-ancestor" ] && exit 1 ;;
  *"cat-file -e"*llm_limit_control*)
    [ -f "$STUB_DIR/old-target" ] || [ -f "$STUB_DIR/pre-limit-target" ] && exit 1 ;;
  *"cat-file -e"*events_and_library_links*)
    [ -f "$STUB_DIR/old-target" ] || [ -f "$STUB_DIR/pre-limit-target" ] \
      || [ -f "$STUB_DIR/pre-library-target" ] && exit 1 ;;
  *"cat-file -e"*) [ -f "$STUB_DIR/old-target" ] && exit 1 ;;
  *"checkout --detach"*) for last; do :; done; echo "$last" > "$STUB_DIR/git-head" ;;
esac
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
if [ ! -x "$STUB_DIR/openssl" ]; then
  cp "$STUB_DIR/openssl.real" "$STUB_DIR/openssl"
  chmod +x "$STUB_DIR/openssl"
fi
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
    _write_executable(stub_dir / "git", _GIT_STUB)
    _write_executable(stub_dir / "curl", _CURL_STUB)
    _write_executable(stub_dir / "sudo", _SUDO_STUB)
    _write_executable(stub_dir / "apt-get", _APT_STUB)
    _write_executable(
        stub_dir / "openssl.real", f'#!/bin/sh\nexec {shutil.which("openssl")} "$@"\n'
    )
    (stub_dir / "os-release").write_text("ID=ubuntu\n")
    return stub_dir


@pytest.fixture
def install_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "opt-tracker"
    (directory / ".git").mkdir(parents=True)
    (directory / ".env.example").write_text("CLIPROXY_VERSION=v8.0.48\nCLIPROXY_API_KEY=\n")
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
        "WAIT_IDLE_POLL_SECONDS": "0",
        "OS_RELEASE_FILE": str(stubs / "os-release"),
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


def _assert_in_order(calls: list[str], expected: list[str]) -> None:
    """Каждый ожидаемый фрагмент — в вызове после предыдущего найденного."""
    position = -1
    for fragment in expected:
        position = next(
            (index for index in range(position + 1, len(calls)) if fragment in calls[index]),
            -1,
        )
        assert position >= 0, f"нет вызова «{fragment}» в нужном порядке: {calls}"


def _env(install_dir: Path) -> dict[str, str]:
    lines = (install_dir / ".env").read_text().splitlines()
    return dict(line.split("=", 1) for line in lines if "=" in line)


def _update(stubs: Path, install_dir: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return _run_bash(
        f'exec bash "{_INSTALL_SCRIPT}" "$@"',
        "--update",
        *args,
        stubs=stubs,
        install_dir=install_dir,
    )


def _make_restore_dir(tmp_path: Path, *, skip: str | None = None) -> Path:
    restore_dir = tmp_path / "transfer"
    restore_dir.mkdir()
    files: dict[str, Callable[[Path], object]] = {
        ".env": lambda path: path.write_text(
            _installed_env(
                SECRET_ENCRYPTION_KEY="старый-ключ",
                SFTP_DB_PASSWORD="",
                CLIPROXY_API_KEY="",
                CLIPROXY_MANAGEMENT_KEY="",
            ),
        ),
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
        "claude_sessions.tar.gz",
        "cliproxy_data.tar.gz",
        "claude_accounts.tar.gz",
        "sftp_host_keys.tar.gz",
    ):
        if archive != skip:
            with tarfile.open(restore_dir / archive, "w:gz"):
                pass
    return restore_dir


def _installed_env(**overrides: str) -> str:
    example = (_INSTALL_SCRIPT.parents[1] / ".env.example").read_text()
    values = {
        key: value or "test-value"
        for line in example.splitlines()
        if line and not line.startswith("#") and "=" in line
        for key, value in [line.split("=", 1)]
    }
    values.update(overrides)
    return "".join(f"{key}={value}\n" for key, value in values.items())


class TestScriptSyntax:
    def test_valid(self) -> None:
        subprocess.run(["bash", "-n", str(_INSTALL_SCRIPT)], check=True)


class TestSharedConstants:
    """Скрипт и backend договариваются о ключе флага и статусах живых сессий."""

    def _value(self, stubs: Path, install_dir: Path, name: str) -> str:
        result = _run_bash(
            f'source "{_INSTALL_SCRIPT}" && printf %s "${name}"',
            stubs=stubs,
            install_dir=install_dir,
        )
        return result.stdout

    def test_maintenance_key(self, stubs: Path, install_dir: Path) -> None:
        assert self._value(stubs, install_dir, "MAINTENANCE_KEY") == MAINTENANCE_KEY

    def test_live_session_statuses(self, stubs: Path, install_dir: Path) -> None:
        raw = self._value(stubs, install_dir, "LIVE_SESSION_STATUSES")
        statuses = {item.strip("'") for item in raw.split(",")}
        assert statuses == {status.value for status in SESSION_ACTIVE_STATUSES}

    def test_pre_launch_statuses_migration(self, stubs: Path, install_dir: Path) -> None:
        """Откат сбрасывает именно статусы, добавленные указанной миграцией."""
        migration = self._value(stubs, install_dir, "PRE_LAUNCH_STATUSES_MIGRATION")
        raw = self._value(stubs, install_dir, "PRE_LAUNCH_STATUSES_ADDED")
        statuses = {item.strip("'") for item in raw.split(",")}
        source = (_INSTALL_SCRIPT.parents[1] / migration).read_text()
        assert all(f'"{status}"' in source for status in statuses)
        assert statuses == {
            TaskStatus.REFINING,
            TaskStatus.DEFINED,
            TaskStatus.READY,
            TaskStatus.NIGHT_WORKER,
        }

    @pytest.mark.parametrize(
        ("migration_variable", "variable", "constant"),
        [
            ("LIMIT_WAIT_MIGRATION", "LIMIT_WAIT_RESET", "_RESTORE_LIMIT_WAITS"),
            ("LIMIT_WAIT_MIGRATION", "LIMIT_SWITCH_REASONS_RESET", "_RESTORE_SWITCH_REASONS"),
            ("LIBRARY_LINKS_MIGRATION", "LIBRARY_CONTENT_RESET", "_RESTORE_LIBRARY_CONTENT"),
            ("LIBRARY_LINKS_MIGRATION", "GUIDE_URL_RESET", "_RESTORE_GUIDE_URL"),
        ],
    )
    def test_downgrade_reset(
        self,
        stubs: Path,
        install_dir: Path,
        migration_variable: str,
        variable: str,
        constant: str,
    ) -> None:
        """Откат возвращает данные в значения прежней версии тем же запросом, что downgrade."""
        migration = self._value(stubs, install_dir, migration_variable)
        query = self._value(stubs, install_dir, variable)
        source = (_INSTALL_SCRIPT.parents[1] / migration).read_text()
        restore = re.search(rf"{constant} = \((.*?)\n\)", source, re.DOTALL)
        assert restore is not None
        assert query == "".join(re.findall(r'"(.*?)"', restore.group(1)))

    def test_backup_components(self, stubs: Path, install_dir: Path) -> None:
        """Архивы копии в S3 — ровно те, что распаковывает --restore (раздел 20.4)."""
        printed = {
            variable: _run_bash(
                f'source "{_INSTALL_SCRIPT}" && printf "%s\\n" "${{{variable}[@]}}"',
                stubs=stubs,
                install_dir=install_dir,
            ).stdout.split()
            for variable in ("RESTORE_ARCHIVES", "RESTORE_OPTIONAL_ARCHIVES")
        }
        names = {
            variable: {mapping.split(":")[0] for mapping in mappings}
            for variable, mappings in printed.items()
        }
        assert names["RESTORE_ARCHIVES"] == {
            component.name for component in COMPONENTS if component.required
        }
        assert names["RESTORE_OPTIONAL_ARCHIVES"] == {
            component.name for component in COMPONENTS if not component.required
        }

    def test_sftp_role_prelude(self, stubs: Path, install_dir: Path) -> None:
        """Проверка восстановления готовит БД так же, как --restore."""
        assert self._value(stubs, install_dir, "SFTP_DB_ROLE_SQL") == SFTP_DB_ROLE_SQL

    def test_after_restore_sql(self, stubs: Path, install_dir: Path) -> None:
        assert self._value(stubs, install_dir, "AFTER_RESTORE_SQL") == AFTER_RESTORE_SQL_NAME

    def test_monitoring_periodic_tasks(self, stubs: Path, install_dir: Path) -> None:
        """Откат удаляет периодическую задачу, которой нет у версии без мониторинга."""
        raw = self._value(stubs, install_dir, "MONITORING_PERIODIC_TASKS")
        names = {item.strip("'") for item in raw.split(",")}
        assert names == {measure_volume_usage.name}

    def test_queue_periodic_tasks(self, stubs: Path, install_dir: Path) -> None:
        """Откат удаляет ровно периодические задачи воркера очереди."""
        raw = self._value(stubs, install_dir, "QUEUE_PERIODIC_TASKS")
        assert {item.strip("'") for item in raw.split(",")} == {
            DISPATCH_READY_TASKS,
            NIGHT_DISPATCH_TASK,
        }


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
        _assert_in_order(
            docker_calls,
            [
                "docker compose build",
                "docker compose up -d --wait postgres redis",
                "docker compose exec -T postgres",
                "task_repos.tar.gz",
                "user_files.tar.gz",
                "log_archive.tar.gz",
                "claude_sessions.tar.gz",
                "cliproxy_data.tar.gz",
                "claude_accounts.tar.gz",
                "sftp_host_keys.tar.gz",
                "docker compose run --rm backend alembic upgrade head",
                # Дамп прежней версии не знает новых периодических задач.
                "seed_periodic_tasks.py",
                "migrate_claude_sessions.py",
                "docker compose up -d cliproxy llm-gateway backend worker session-worker"
                " backup-worker beat sftp frontend caddy backup",
            ],
        )
        # Администратор и allowlist — из дампа.
        assert not any("seed_admin" in call for call in docker_calls)
        # Роль SFTP-шлюза — до дампа: в нём есть права на неё (раздел 20.4).
        assert (stubs / "psql-input").read_text() == f"{SFTP_DB_ROLE_SQL}\n-- fresh dump\n"
        assert not any("checkout" in call for call in _calls(stubs))
        # Ключи старого сервера сохранены; пароль роли шлюза и ключи прокси
        # .env прежней версии не знал — они дописаны.
        env = _env(install_dir)
        assert env["SECRET_ENCRYPTION_KEY"] == "старый-ключ"
        assert len(env["SFTP_DB_PASSWORD"]) == 48
        assert len(env["CLIPROXY_MANAGEMENT_KEY"]) == 64
        # Volume ключа хоста у backend только для чтения, учётки прокси — только у прокси.
        for archive, service in [("sftp_host_keys", "sftp"), ("cliproxy_data", "cliproxy-init")]:
            [call] = [call for call in docker_calls if f"{archive}.tar.gz" in call]
            assert f"--entrypoint sh {service}" in call

    def test_after_restore_sql_follows_dump(
        self,
        tmp_path: Path,
        stubs: Path,
        install_dir: Path,
    ) -> None:
        """Копия из S3 закрывает запуск бэкапа, во время которого снят дамп."""
        restore_dir = _make_restore_dir(tmp_path)
        (restore_dir / AFTER_RESTORE_SQL_NAME).write_text("-- after restore\n")

        result = _run_bash(
            f'exec bash "{_INSTALL_SCRIPT}" "$@"',
            "--restore",
            str(restore_dir),
            stubs=stubs,
            install_dir=install_dir,
        )

        assert result.returncode == 0, result.stdout + result.stderr
        assert (stubs / "psql-input").read_text() == (
            f"{SFTP_DB_ROLE_SQL}\n-- fresh dump\n-- after restore\n"
        )

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

    @pytest.mark.parametrize(
        "archive",
        ["claude_accounts.tar.gz", "claude_sessions.tar.gz", "cliproxy_data.tar.gz"],
    )
    def test_optional_archive_missing(
        self,
        tmp_path: Path,
        stubs: Path,
        install_dir: Path,
        archive: str,
    ) -> None:
        """Перенос с сервера другой версии: такого volume там не было."""
        restore_dir = _make_restore_dir(tmp_path, skip=archive)

        result = _run_bash(
            f'exec bash "{_INSTALL_SCRIPT}" "$@"',
            "--restore",
            str(restore_dir),
            stubs=stubs,
            install_dir=install_dir,
        )

        assert result.returncode == 0, result.stdout + result.stderr
        assert f"{archive} нет в переносе" in result.stdout
        docker_calls = [call for call in _calls(stubs) if call.startswith("docker")]
        assert any("log_archive.tar.gz" in call for call in docker_calls)
        assert not any(archive in call for call in docker_calls)

    def test_ref(self, tmp_path: Path, stubs: Path, install_dir: Path) -> None:
        """Копия из S3 восстанавливается на той версии кода, на которой снята."""
        result = _run_bash(
            f'exec bash "{_INSTALL_SCRIPT}" "$@"',
            "--restore",
            str(_make_restore_dir(tmp_path)),
            "--ref",
            "abc1234",
            stubs=stubs,
            install_dir=install_dir,
        )

        assert result.returncode == 0, result.stdout + result.stderr
        _assert_in_order(
            _calls(stubs),
            [
                "fetch origin",
                "rev-parse --verify --quiet abc1234^{commit}",
                "merge-base --is-ancestor",
                f"checkout --detach {_TARGET_SHA}",
                "docker compose build",
                "docker compose exec -T postgres",
            ],
        )

    def test_ref_outside_main(self, tmp_path: Path, stubs: Path, install_dir: Path) -> None:
        (stubs / "not-ancestor").touch()

        result = _run_bash(
            f'exec bash "{_INSTALL_SCRIPT}" "$@"',
            "--restore",
            str(_make_restore_dir(tmp_path)),
            "--ref",
            "abc1234",
            stubs=stubs,
            install_dir=install_dir,
        )

        assert result.returncode != 0
        assert "origin/main" in result.stdout
        assert not any(call.startswith("docker compose build") for call in _calls(stubs))

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

    @pytest.fixture(autouse=True)
    def installed(self, install_dir: Path) -> None:
        (install_dir / ".env").write_text(
            _installed_env(
                REDIS_PASSWORD=_REDIS_PASSWORD,
                CLIPROXY_VERSION="v1.0.0",
                CLIPROXY_API_KEY="",
                CLIPROXY_MANAGEMENT_KEY="",
                GIT_SHA=_PREVIOUS_SHA,
            ),
        )
        # Скрипт «полученного» коммита: заглушка git не меняет файлы.
        (install_dir / "deploy").mkdir()
        shutil.copy(_INSTALL_SCRIPT, install_dir / "deploy" / "install.sh")

    def test_steps_in_order(self, stubs: Path, install_dir: Path) -> None:
        result = _update(stubs, install_dir)

        assert result.returncode == 0, result.stdout + result.stderr
        calls = _calls(stubs)
        _assert_in_order(
            calls,
            [
                "docker compose up -d --wait postgres redis",
                "redis-cli SET maintenance:deploy 1 EX 3600",
                "fetch origin",
                "rev-parse --verify --quiet origin/main^{commit}",
                f"merge-base --is-ancestor {_TARGET_SHA} origin/main",
                f"checkout --detach {_TARGET_SHA}",
                "docker compose build",
                "docker build -t tracker-runner-python:latest",
                "docker build -t tracker-runner-bash:latest",
                "docker build -t tracker-session:latest",
                "docker compose up -d --wait postgres redis",
                "redis-cli SET maintenance:deploy",
                "exec -T backup /usr/local/bin/backup.sh",
                "alembic upgrade head",
                "seed_periodic_tasks.py",
                "migrate_claude_sessions.py",
                "docker compose up -d cliproxy llm-gateway backend worker session-worker"
                " backup-worker beat sftp",
                "redis-cli DEL maintenance:deploy",
            ],
        )
        assert not any("seed_admin_allowlist" in call or "git clone" in call for call in calls)
        assert not any(_REDIS_PASSWORD in call for call in calls)
        assert not any("psql" in call for call in calls)
        env = _env(install_dir)
        assert (env["GIT_SHA"], env["CLIPROXY_VERSION"]) == (_TARGET_SHA, "v8.0.48")
        assert len(env["CLIPROXY_API_KEY"]) == 64
        assert (install_dir / ".env").read_text().count("SFTP_DB_PASSWORD=") == 1
        previous_ref = install_dir / ".deploy" / "previous_ref"
        assert previous_ref.read_text().strip() == _PREVIOUS_SHA
        assert sum("fetch origin" in call for call in calls) == 1
        assert "продолжает install.sh новой версии" in result.stdout

    @pytest.mark.parametrize(
        ("marker", "resumed"),
        [
            pytest.param("# TRACKER_UPDATE_FETCHED", True, id="новая версия продолжает"),
            pytest.param("", False, id="версия без продолжения"),
        ],
    )
    def test_fetched_script(
        self,
        stubs: Path,
        install_dir: Path,
        marker: str,
        resumed: bool,
    ) -> None:
        # Имя флага собирается по частям, чтобы метку содержал только marker.
        _write_executable(
            install_dir / "deploy" / "install.sh",
            f"#!/bin/sh\n{marker}\n"
            'eval "resume=\\${TRACKER_UPDATE_""FETCHED:-}"\n'
            'echo "fetched $* resume=$resume" >> "$STUB_LOG"\n',
        )

        result = _update(stubs, install_dir, "--ref", "abc1234")

        assert result.returncode == 0, result.stdout + result.stderr
        calls = _calls(stubs)
        fetched = [call for call in calls if call.startswith("fetched")]
        assert fetched == (["fetched --update --ref abc1234 resume=1"] if resumed else [])
        assert any("compose build" in call for call in calls) is not resumed
        # Флаг обслуживания снимает уже продолжившая версия.
        assert any("redis-cli DEL" in call for call in calls) is not resumed
        _assert_in_order(calls, ["checkout --detach", "fetched" if resumed else "compose build"])
        previous_ref = install_dir / ".deploy" / "previous_ref"
        assert previous_ref.read_text().strip() == _PREVIOUS_SHA

    def test_ref(self, stubs: Path, install_dir: Path) -> None:
        result = _update(stubs, install_dir, "--ref", "abc1234")

        assert result.returncode == 0, result.stdout + result.stderr
        assert any("rev-parse --verify --quiet abc1234^{commit}" in call for call in _calls(stubs))

    def test_ref_outside_main(self, stubs: Path, install_dir: Path) -> None:
        (stubs / "not-ancestor").touch()

        result = _update(stubs, install_dir, "--ref", "abc1234")

        assert result.returncode == 3
        assert "origin/main" in result.stdout
        calls = _calls(stubs)
        assert not any("checkout" in call or "compose build" in call for call in calls)
        assert "redis-cli DEL maintenance:deploy" in calls[-1]
        assert not (install_dir / ".deploy").exists()

    @pytest.mark.parametrize(
        ("target", "limit_reset", "pre_launch_reset", "library_reset"),
        [
            pytest.param(
                "old-target", True, True, True, id="откат на версию без статусов до запуска",
            ),
            pytest.param(
                "pre-limit-target", True, False, True, id="откат на версию без ожидания лимита",
            ),
            pytest.param(
                "pre-library-target",
                False,
                False,
                True,
                id="откат на версию без ссылок на библиотеку",
            ),
            pytest.param(None, False, False, False, id="версия со всеми изменениями"),
        ],
    )
    def test_unknown_statuses_reset(
        self,
        stubs: Path,
        install_dir: Path,
        target: str | None,
        limit_reset: bool,
        pre_launch_reset: bool,
        library_reset: bool,
    ) -> None:
        if target is not None:
            (stubs / target).touch()

        result = _update(stubs, install_dir, "--ref", "abc1234")

        assert result.returncode == 0, result.stdout + result.stderr
        calls = _calls(stubs)
        assert any("cat-file -e" in call for call in calls)
        resets_seen = [call for call in calls if "psql" in call and "UPDATE" in call]
        assert len(resets_seen) == int(limit_reset or pre_launch_reset or library_reset)
        reset = resets_seen[0] if resets_seen else ""
        assert ("FROM nodes AS library_items" in reset) is library_reset
        assert ("node[.]guide_url" in reset) is library_reset
        assert ("WHERE name IN ('measure_volume_usage')" in reset) is library_reset
        assert ("WHERE status::text = 'awaiting_limit'" in reset) is limit_reset
        assert ("UPDATE node_logs SET llm_switch_reason" in reset) is limit_reset
        assert ("UPDATE tasks SET status = 'new'" in reset) is pre_launch_reset
        if pre_launch_reset:
            assert "'refining','defined','ready','night_worker'" in reset
            assert "'dispatch_ready_tasks','dispatch_night_tasks'" in reset
            # Ждущие чата задачи сначала уходят в refining, затем — в new.
            assert reset.index("awaiting_limit") < reset.index("status = 'new'")
        if resets_seen:
            _assert_in_order(calls, ["checkout --detach", "cat-file -e", "UPDATE"])

    def test_failed_reset_restores_code(self, stubs: Path, install_dir: Path) -> None:
        (stubs / "old-target").touch()
        (stubs / "fail-reset").touch()

        result = _update(stubs, install_dir, "--ref", "abc1234")

        assert result.returncode == 3
        assert "сервер не изменён" in result.stdout
        calls = _calls(stubs)
        _assert_in_order(
            calls,
            [
                f"checkout --detach {_TARGET_SHA}",
                "UPDATE tasks",
                f"checkout --detach {_PREVIOUS_SHA}",
            ],
        )
        assert not any("compose build" in call for call in calls)

    def test_waits_for_idle(self, stubs: Path, install_dir: Path) -> None:
        (stubs / "live-sessions").write_text("2\n1\n0\n")

        result = _update(stubs, install_dir, "--wait-idle", "5")

        assert result.returncode == 0, result.stdout + result.stderr
        calls = _calls(stubs)
        assert sum("psql" in call for call in calls) == 3
        assert "redis-cli SET maintenance:deploy 1 EX 3900" in "\n".join(calls)
        _assert_in_order(calls, ["redis-cli SET", "psql", "fetch origin"])

    def test_wait_idle_timeout(self, stubs: Path, install_dir: Path) -> None:
        (stubs / "live-sessions").write_text("1\n")

        result = _update(stubs, install_dir, "--wait-idle", "0")

        assert result.returncode == 3
        assert "не завершились" in result.stdout
        calls = _calls(stubs)
        assert not any("fetch" in call or "compose build" in call for call in calls)
        assert "redis-cli DEL maintenance:deploy" in calls[-1]

    def test_requires_installation(self, stubs: Path, install_dir: Path) -> None:
        (install_dir / ".env").unlink()

        result = _update(stubs, install_dir)

        assert result.returncode != 0
        assert not any(call.startswith("docker") for call in _calls(stubs))

    def test_not_with_restore(self, tmp_path: Path, stubs: Path, install_dir: Path) -> None:
        result = _update(stubs, install_dir, "--restore", str(_make_restore_dir(tmp_path)))

        assert result.returncode == 2

    @pytest.mark.parametrize(
        "args",
        [
            ["--ref", "abc1234"],
            ["--wait-idle", "5"],
            ["--update", "--ref", "main;reboot"],
            ["--update", "--ref", "origin/main"],
            ["--update", "--wait-idle", "soon"],
        ],
        ids=["ref_without_update", "wait_without_update", "ref_injection", "ref_name", "minutes"],
    )
    def test_bad_arguments(self, stubs: Path, install_dir: Path, args: list[str]) -> None:
        result = _run_bash(
            f'exec bash "{_INSTALL_SCRIPT}" "$@"',
            *args,
            stubs=stubs,
            install_dir=install_dir,
        )

        assert result.returncode == 2
        assert _calls(stubs) == []


class TestPrepareEnv:
    """Ключи прокси генерируются один раз, версия прокси и коммит — из репозитория."""

    def test_values(self, stubs: Path, install_dir: Path) -> None:
        (install_dir / ".env").write_text(
            "CLIPROXY_API_KEY=keep\nCLIPROXY_VERSION=v1.0.0\nGIT_SHA=\n",
        )

        result = _run_bash(
            f'source "{_INSTALL_SCRIPT}" && step_prepare_env_for_build',
            stubs=stubs,
            install_dir=install_dir,
        )

        assert result.returncode == 0, result.stdout + result.stderr
        env = _env(install_dir)
        assert (env["CLIPROXY_API_KEY"], env["CLIPROXY_VERSION"]) == ("keep", "v8.0.48")
        assert env["GIT_SHA"] == _PREVIOUS_SHA
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", env["DEPLOYED_AT"])
        assert env["CLIPROXY_MANAGEMENT_KEY"].isalnum()
        assert len(env["CLIPROXY_MANAGEMENT_KEY"]) == 64


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


class TestHostDependencies:
    def test_installs_missing_openssl(self, stubs: Path, install_dir: Path) -> None:
        (stubs / "openssl").unlink()
        result = _run_bash(
            f'source "{_INSTALL_SCRIPT}" && step_install_host_dependencies',
            stubs=stubs,
            install_dir=install_dir,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert "apt-get install -y git curl openssl ca-certificates" in _calls(stubs)
        assert os.access(stubs / "openssl", os.X_OK)

    @pytest.mark.parametrize("distro", ["almalinux", "rocky"])
    def test_rpm_docker_install(self, stubs: Path, install_dir: Path, distro: str) -> None:
        (stubs / "docker").unlink()
        (stubs / "os-release").write_text(f"ID={distro}\n")
        _write_executable(
            stubs / "dnf",
            '#!/bin/sh\necho "dnf $*" >> "$STUB_LOG"\n'
            'case "$*" in *docker-ce-cli*) cp "$STUB_DIR/docker.real" "$STUB_DIR/docker"; '
            'chmod +x "$STUB_DIR/docker";; esac\n',
        )
        _write_executable(stubs / "systemctl", _LOGGING_STUB.format(name="systemctl"))
        result = _run_bash(
            f'source "{_INSTALL_SCRIPT}" && step_install_docker',
            stubs=stubs,
            install_dir=install_dir,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        calls = _calls(stubs)
        _assert_in_order(
            calls,
            [
                "dnf install -y dnf-plugins-core",
                "dnf config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo",
                "dnf install -y docker-ce docker-ce-cli containerd.io",
                "systemctl enable --now docker",
            ],
        )
        assert not any("get.docker.com" in call for call in calls)


class TestInvalidEnv:
    @pytest.mark.parametrize(
        "key", ["POSTGRES_PASSWORD", "GOOGLE_OAUTH_CLIENT_ID", "SESSION_SECRET_KEY"]
    )
    @pytest.mark.parametrize("value", ["", '""', "''"])
    def test_stops_before_build(
        self,
        stubs: Path,
        install_dir: Path,
        key: str,
        value: str,
    ) -> None:
        (install_dir / ".env").write_text(_installed_env(**{key: value}))
        result = _run_bash(
            f'source "{_INSTALL_SCRIPT}" && step_build_images',
            stubs=stubs,
            install_dir=install_dir,
        )
        assert result.returncode != 0
        assert key in result.stdout
        assert "test-value" not in result.stdout + result.stderr
        assert _calls(stubs) == []

    def test_failed_generator_does_not_write_empty_secret(
        self,
        stubs: Path,
        install_dir: Path,
    ) -> None:
        (install_dir / ".env.example").write_text("SECRET_ENCRYPTION_KEY=\n")
        (stubs / "openssl").unlink()
        _write_executable(stubs / "openssl", "#!/bin/sh\nexit 1\n")
        result = _run_bash(
            f'source "{_INSTALL_SCRIPT}" && step_generate_env',
            stubs=stubs,
            install_dir=install_dir,
        )
        assert result.returncode != 0
        assert "SECRET_ENCRYPTION_KEY" in result.stdout
        assert not any("docker run" in call for call in _calls(stubs))
        assert (install_dir / ".env").stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("legacy", [False, True], ids=["с чатом", "прежняя схема"])
async def test_deploy_live_count_supports_chat_and_legacy_schema(
    db_session: AsyncSession,
    legacy: bool,
) -> None:
    source = _INSTALL_SCRIPT.read_text()
    statuses = re.search(r'^LIVE_SESSION_STATUSES="(.*)"', source, re.MULTILINE)
    function = source.split("_live_session_count() {", 1)[1].split("\n}", 1)[0]
    query = re.search(r'local query="(.*)"', function)
    assert statuses is not None and query is not None
    sql = query[1].replace("${LIVE_SESSION_STATUSES}", statuses[1])
    sql = sql.replace("tasks", "deploy_live_count_test")
    chat_column = "" if legacy else ", chat_active boolean NOT NULL DEFAULT false"
    await db_session.execute(
        sa.text(
            f"CREATE TEMP TABLE deploy_live_count_test (status text{chat_column}) ON COMMIT DROP",
        )
    )
    if legacy:
        values = "('new'), ('in_progress')"
        columns = "status"
    else:
        values = "('refining', true), ('refining', false), ('new', false)"
        columns = "status, chat_active"
    await db_session.execute(
        sa.text(
            f"INSERT INTO deploy_live_count_test ({columns}) VALUES {values}",
        )
    )
    assert await db_session.scalar(sa.text(sql)) == 1
