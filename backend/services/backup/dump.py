"""
Дамп БД для копии (раздел 20.4 ТЗ): `pg_dump --format=plain` → `gzip`, тот
же формат, что у контейнера `backup` и `install.sh --restore`.

Число строк каждой таблицы и версия схемы снимаются в том же снимке БД, что
и дамп (`pg_export_snapshot` → `pg_dump --snapshot`): еженедельная проверка
сверяет с ними восстановленную базу, и запись, добавленная во время бэкапа,
не даёт ложного расхождения.

Права (`GRANT`) в дамп не попадают: на новом сервере роли SFTP-шлюза ещё нет
до первого старта backend, а её права заново выдаёт entrypoint при каждом
старте (`sftp_gateway/db_role.py`).
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import sqlalchemy as sa

from app_logging.config import get_logger

if TYPE_CHECKING:
    from sqlalchemy.engine import URL
    from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

logger = get_logger("backup_dump")

DUMP_ATTEMPTS = 3
DUMP_RETRY_DELAY_SECONDS = 30.0
_PG_DUMP_ARGS = ("--format=plain", "--no-privileges")


class DumpError(Exception):
    """Дамп не снят — причина без пароля БД."""


@dataclass(frozen=True, slots=True)
class DumpCommand:
    argv: list[str]
    env: dict[str, str]


# По идентификатору снимка — команда pg_dump, которая пишет дамп в stdout.
DumpCommandFactory = Callable[[str], DumpCommand]


@dataclass(frozen=True, slots=True)
class DumpResult:
    path: Path
    alembic_version: str | None
    table_counts: dict[str, int]
    database: str
    user: str


def pg_dump_command(url: URL) -> DumpCommandFactory:
    """pg_dump образа backend; параметры подключения — через окружение `PG*`, не argv."""
    env = {
        "PGHOST": url.host or "localhost",
        "PGPORT": str(url.port or 5432),
        "PGUSER": url.username or "",
        "PGPASSWORD": url.password or "",
        "PGDATABASE": url.database or "",
    }

    def build(snapshot: str) -> DumpCommand:
        return DumpCommand(
            argv=["pg_dump", *_PG_DUMP_ARGS, f"--snapshot={snapshot}"],
            env={**os.environ, **env},
        )

    return build


def pg_dump_args(snapshot: str) -> list[str]:
    """Аргументы pg_dump для своей команды (тесты: `docker exec … pg_dump`)."""
    return [*_PG_DUMP_ARGS, f"--snapshot={snapshot}"]


def _quote_identifier(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


async def _snapshot_state(connection: AsyncConnection) -> tuple[str, str | None, dict[str, int]]:
    snapshot = (await connection.execute(sa.text("SELECT pg_export_snapshot()"))).scalar_one()
    tables = (
        await connection.execute(
            sa.text(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename",
            ),
        )
    ).scalars()
    counts: dict[str, int] = {}
    for table in list(tables):
        counts[table] = (
            await connection.execute(sa.text(f"SELECT count(*) FROM {_quote_identifier(table)}"))
        ).scalar_one()
    version = None
    if "alembic_version" in counts:
        version = (
            await connection.execute(sa.text("SELECT version_num FROM alembic_version"))
        ).scalar_one_or_none()
    return str(snapshot), version, counts


async def _run_pg_dump(command: DumpCommand, target: Path) -> None:
    """`pg_dump | gzip > target` без промежуточного несжатого файла."""
    read_fd, write_fd = os.pipe()
    try:
        with target.open("wb") as output:
            gzip_process = await asyncio.create_subprocess_exec(
                "gzip",
                "-c",
                stdin=read_fd,
                stdout=output,
            )
            dump_process = await asyncio.create_subprocess_exec(
                *command.argv,
                stdout=write_fd,
                stderr=asyncio.subprocess.PIPE,
                env=command.env,
            )
            os.close(write_fd)
            write_fd = -1
            os.close(read_fd)
            read_fd = -1
            _, stderr = await dump_process.communicate()
            await gzip_process.wait()
    finally:
        for fd in (read_fd, write_fd):
            if fd >= 0:
                os.close(fd)
    if dump_process.returncode != 0:
        raise DumpError(f"pg_dump завершился с кодом {dump_process.returncode}: {stderr.decode()}")
    if gzip_process.returncode != 0:
        raise DumpError(f"gzip завершился с кодом {gzip_process.returncode}")


async def _dump_once(
    engine: AsyncEngine,
    target: Path,
    command_factory: DumpCommandFactory,
) -> DumpResult:
    async with engine.connect() as connection:
        connection = await connection.execution_options(isolation_level="REPEATABLE READ")
        async with connection.begin():
            snapshot, version, counts = await _snapshot_state(connection)
            # Снимок жив, пока открыта эта транзакция.
            await _run_pg_dump(command_factory(snapshot), target)
    return DumpResult(
        path=target,
        alembic_version=version,
        table_counts=counts,
        database=engine.url.database or "",
        user=engine.url.username or "",
    )


async def dump_database(
    engine: AsyncEngine,
    target: Path,
    *,
    command_factory: DumpCommandFactory,
    attempts: int = DUMP_ATTEMPTS,
    retry_delay_seconds: float = DUMP_RETRY_DELAY_SECONDS,
) -> DumpResult:
    """Снимает дамп с повторами: обрыв соединения с БД не срывает бэкап."""
    for attempt in range(1, attempts + 1):
        try:
            result = await _dump_once(engine, target, command_factory)
        except (DumpError, OSError, sa.exc.DBAPIError) as exc:
            target.unlink(missing_ok=True)
            if attempt == attempts:
                raise DumpError(f"Не удалось снять дамп БД: {exc}") from exc
            logger.warning("backup_dump_retry", attempt=attempt, error=type(exc).__name__)
            await asyncio.sleep(retry_delay_seconds)
            continue
        logger.info("backup_dump_done", tables=len(result.table_counts))
        return result
    raise AssertionError("unreachable")
