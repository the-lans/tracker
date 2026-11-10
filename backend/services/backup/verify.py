"""
Еженедельная проверка восстановления (`verify_s3_backup`, раздел 20.4 ТЗ).

Последняя копия скачивается и проверяется так, как её восстанавливал бы
`restore.sh` на новом сервере: SHA-256 объекта, расшифровка паролем,
`SHA256SUMS`, полное чтение каждого архива volume (число файлов — как в
`manifest.json`) и загрузка дампа в пустой PostgreSQL той же версии, что у
сервера, — с теми же ролью-владельцем и подготовкой, что у
`install.sh --restore`, и с `ON_ERROR_STOP`. Затем версия схемы и число
строк каждой таблицы сверяются с `manifest.json`.

PostgreSQL проверки — временный контейнер без сети, с меткой: его остатки
после прерванного запуска удаляются следующим.
"""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import tarfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app_logging.config import get_logger
from db.models.enums import BackupRunKind, BackupRunStatus
from services.backup.bundle import (
    AFTER_RESTORE_SQL_NAME,
    BUNDLE_PREFIX,
    CHECKSUMS_NAME,
    ENV_NAME,
    MANIFEST_NAME,
    RESTORE_GUIDE_NAME,
    RESTORE_SCRIPT_NAME,
)
from services.backup.crypto_gpg import decrypt_to_directory
from services.backup.files import READ_CHUNK_BYTES, sha256_file
from services.backup.runner import SPACE_MARGIN_BYTES, clear_staging, ensure_space
from services.backup.runs import (
    BACKUP_LOCK_WAIT_SECONDS,
    BackupError,
    backup_lock,
    close_interrupted_runs,
    fail_run,
    failure_message,
    finish_run,
    start_run,
)
from services.backup.storage import S3Storage, StoredObject
from services.notifications import NotificationEvent

if TYPE_CHECKING:
    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncSession

    from db.models.backups import BackupRun
    from services.backup.settings import BackupConfig

logger = get_logger("backup_verify")

# Та же major-версия, что у сервиса postgres в docker-compose.yml.
VERIFY_POSTGRES_IMAGE = "postgres:15-alpine"
VERIFY_CONTAINER_LABEL = "tracker.backup-verify"
# Та же подготовка, что у install.sh --restore (SFTP_DB_ROLE_SQL, тест сверяет).
SFTP_DB_ROLE_SQL = (
    "DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'tracker_sftp') "
    "THEN CREATE ROLE tracker_sftp NOLOGIN; END IF; END $$;"
)
DEFAULT_READY_TIMEOUT_SECONDS = 180.0
DEFAULT_LOAD_TIMEOUT_SECONDS = 2 * 60 * 60.0
_READY_POLL_SECONDS = 1.0
# Скачанный объект + распакованная копия + данные временного PostgreSQL.
_VERIFY_SPACE_FACTOR = 3
_EXTRACT_DIR = "extracted"
_REQUIRED_FILES = (ENV_NAME, MANIFEST_NAME, RESTORE_SCRIPT_NAME, RESTORE_GUIDE_NAME)
_ERROR_TAIL_CHARS = 2000


@dataclass(frozen=True, slots=True)
class VerifyEnvironment:
    staging: Path
    postgres_image: str = VERIFY_POSTGRES_IMAGE
    ready_timeout_seconds: float = DEFAULT_READY_TIMEOUT_SECONDS
    load_timeout_seconds: float = DEFAULT_LOAD_TIMEOUT_SECONDS
    lock_wait_seconds: float = BACKUP_LOCK_WAIT_SECONDS


async def _run(*argv: str, timeout: float | None = None) -> tuple[int, str, str]:
    process = await asyncio.create_subprocess_exec(
        *argv,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except TimeoutError:
        process.kill()
        await process.wait()
        raise
    return process.returncode or 0, stdout.decode(), stderr.decode(errors="replace")


async def _download(storage: S3Storage, staging: Path) -> tuple[StoredObject, Path]:
    backups = await storage.list_backups()
    if not backups:
        raise BackupError("В хранилище нет ни одной копии")
    name = storage.name_of(backups[-1])
    stored = await storage.head(name)
    if stored is None:
        raise BackupError(f"Копия {name} пропала из хранилища")
    if not stored.sha256:
        raise BackupError(f"У копии {name} нет SHA-256 в метаданных")
    ensure_space(staging, stored.size * _VERIFY_SPACE_FACTOR + SPACE_MARGIN_BYTES)
    path = staging / name
    await storage.download(name, path)
    if path.stat().st_size != stored.size:
        raise BackupError(f"Размер скачанной копии {name} не совпадает с хранилищем")
    if await asyncio.to_thread(sha256_file, path) != stored.sha256:
        raise BackupError(f"SHA-256 копии {name} не совпадает с записанной при загрузке")
    return stored, path


def _bundle_directory(extracted: Path) -> Path:
    found = [
        child
        for child in extracted.iterdir()
        if child.is_dir() and child.name.startswith(BUNDLE_PREFIX)
    ]
    if len(found) != 1:
        raise BackupError("В копии нет каталога tracker-backup-*")
    return found[0]


def check_checksums(directory: Path) -> int:
    """Сверяет `SHA256SUMS`; отдаёт число проверенных файлов."""
    sums = directory / CHECKSUMS_NAME
    if not sums.is_file():
        raise BackupError("В копии нет SHA256SUMS")
    mismatched: list[str] = []
    lines = [line for line in sums.read_text().splitlines() if line.strip()]
    for line in lines:
        expected, name = line.split("  ", 1)
        path = directory / name
        if not path.is_file() or sha256_file(path) != expected:
            mismatched.append(name)
    if mismatched:
        raise BackupError(f"Не сошлись контрольные суммы: {', '.join(mismatched)}")
    missing = [name for name in _REQUIRED_FILES if not (directory / name).is_file()]
    if missing:
        raise BackupError(f"В копии нет файлов: {', '.join(missing)}")
    return len(lines)


def count_archive_files(path: Path) -> int:
    """Читает архив целиком (проверяя gzip) и считает обычные файлы."""
    files = 0
    with tarfile.open(path, "r:gz") as tar:
        for member in tar:
            if member.isreg():
                stream = tar.extractfile(member)
                if stream is not None:
                    while stream.read(READ_CHUNK_BYTES):
                        pass
                files += 1
    return files


def check_archives(directory: Path, manifest: dict[str, Any]) -> list[dict[str, Any]]:
    checked: list[dict[str, Any]] = []
    for component in manifest["components"]:
        if not component["present"]:
            continue
        path = directory / component["file"]
        try:
            files = count_archive_files(path)
        except (OSError, tarfile.TarError, EOFError) as exc:
            raise BackupError(f"Архив {component['file']} не читается: {exc}") from exc
        if files != component["files"]:
            raise BackupError(
                f"В архиве {component['file']} {files} файлов, в manifest — {component['files']}",
            )
        checked.append({"name": component["name"], "files": files})
    return checked


class TemporaryPostgres:
    """PostgreSQL проверки в контейнере без сети; только роль-владелец, как на новом сервере."""

    def __init__(self, environment: VerifyEnvironment, *, user: str, database: str) -> None:
        self._environment = environment
        self._user = user
        self._database = database
        self._container: str | None = None

    async def __aenter__(self) -> TemporaryPostgres:
        await remove_leftover_containers()
        code, stdout, stderr = await _run(
            "docker",
            "run",
            "-d",
            "--rm",
            "--network",
            "none",
            "--label",
            f"{VERIFY_CONTAINER_LABEL}=1",
            "-e",
            f"POSTGRES_USER={self._user}",
            "-e",
            f"POSTGRES_DB={self._database}",
            "-e",
            f"POSTGRES_PASSWORD={secrets.token_hex(16)}",
            self._environment.postgres_image,
        )
        if code != 0:
            raise BackupError(f"Не удалось запустить PostgreSQL проверки: {stderr.strip()}")
        self._container = stdout.strip()
        try:
            await self._wait_ready()
        except BaseException:
            # Исключение в __aenter__ не вызывает __aexit__: контейнер не должен
            # жить до следующей проверки.
            await self.__aexit__()
            raise
        return self

    async def __aexit__(self, *_: object) -> None:
        if self._container:
            await _run("docker", "rm", "-f", self._container)

    @property
    def container(self) -> str:
        if self._container is None:
            raise BackupError("PostgreSQL проверки не запущен")
        return self._container

    async def _wait_ready(self) -> None:
        # Через TCP: во время инициализации образ слушает только сокет, а затем
        # перезапускает сервер — готовность по сокету была бы ложной.
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._environment.ready_timeout_seconds
        while loop.time() < deadline:
            code, _, _ = await _run(
                "docker",
                "exec",
                self.container,
                "pg_isready",
                "-h",
                "127.0.0.1",
                "-U",
                self._user,
                "-d",
                self._database,
            )
            if code == 0:
                return
            await asyncio.sleep(_READY_POLL_SECONDS)
        raise BackupError("PostgreSQL проверки не запустился вовремя")

    def _psql(self, *args: str) -> list[str]:
        return [
            "docker",
            "exec",
            "-i",
            self.container,
            "psql",
            "-X",
            "-q",
            "-v",
            "ON_ERROR_STOP=1",
            "-U",
            self._user,
            "-d",
            self._database,
            *args,
        ]

    async def load(self, dump: Path, staging: Path, *, after_restore: Path) -> None:
        """
        Как install.sh: роль SFTP-шлюза, дамп, затем `after-restore.sql`
        копии — psql с ON_ERROR_STOP.
        """
        prelude = staging / "prelude.sql"
        prelude.write_text(SFTP_DB_ROLE_SQL + "\n")
        read_fd, write_fd = os.pipe()
        try:
            producer = await asyncio.create_subprocess_exec(
                "sh",
                "-c",
                'cat "$1" && gzip -dc "$2" && cat "$3"',
                "sh",
                str(prelude),
                str(dump),
                str(after_restore),
                stdout=write_fd,
            )
            consumer = await asyncio.create_subprocess_exec(
                *self._psql(),
                stdin=read_fd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
        finally:
            os.close(read_fd)
            os.close(write_fd)
        try:
            _, stderr = await asyncio.wait_for(
                consumer.communicate(),
                timeout=self._environment.load_timeout_seconds,
            )
        except TimeoutError as exc:
            consumer.kill()
            producer.kill()
            raise BackupError("Дамп не загрузился за отведённое время") from exc
        await producer.wait()
        # Сначала psql: остановившись на ошибке, он закрывает канал, и
        # распаковка тоже падает — но причина в SQL, а не в архиве.
        if consumer.returncode != 0:
            tail = stderr.decode(errors="replace").strip()[-_ERROR_TAIL_CHARS:]
            raise BackupError(f"Дамп не загрузился в чистый PostgreSQL: {tail}")
        if producer.returncode != 0:
            raise BackupError("Дамп не распаковывается (gzip)")

    async def query(self, sql: str) -> list[str]:
        code, stdout, stderr = await _run(*self._psql("-tA", "-c", sql))
        if code != 0:
            raise BackupError(f"Запрос к восстановленной БД не прошёл: {stderr.strip()}")
        return [line for line in stdout.splitlines() if line]


async def remove_leftover_containers() -> None:
    _, stdout, _ = await _run(
        "docker",
        "ps",
        "-aq",
        "--filter",
        f"label={VERIFY_CONTAINER_LABEL}",
    )
    for container in stdout.split():
        await _run("docker", "rm", "-f", container)


def _quote_identifier(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _quote_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


async def compare_database(postgres: TemporaryPostgres, database: dict[str, Any]) -> int:
    """Версия схемы и число строк каждой таблицы — как в manifest; отдаёт число строк."""
    expected: dict[str, int] = database["table_counts"]
    tables = set(
        await postgres.query(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename",
        ),
    )
    if tables != set(expected):
        missing = sorted(set(expected) - tables)
        extra = sorted(tables - set(expected))
        raise BackupError(f"Таблицы не совпадают с manifest: нет {missing}, лишние {extra}")
    if expected:
        union = " UNION ALL ".join(
            f"SELECT {_quote_literal(name)}, count(*) FROM {_quote_identifier(name)}"
            for name in sorted(expected)
        )
        actual = {
            name: int(count)
            for name, count in (line.split("|", 1) for line in await postgres.query(union))
        }
        differing = sorted(name for name in expected if actual.get(name) != expected[name])
        if differing:
            raise BackupError(f"Число строк не совпадает с manifest: {', '.join(differing)}")
    if database.get("alembic_version"):
        [version] = await postgres.query("SELECT version_num FROM alembic_version")
        if version != database["alembic_version"]:
            raise BackupError("Версия схемы восстановленной БД не совпадает с manifest")
    return sum(expected.values())


def _after_restore_sql(directory: Path) -> Path:
    """В копиях первых версий файла нет — как в install.sh, без него."""
    path = directory / AFTER_RESTORE_SQL_NAME
    return path if path.is_file() else Path(os.devnull)


async def _verify(
    *,
    config: BackupConfig,
    storage: S3Storage,
    environment: VerifyEnvironment,
) -> tuple[StoredObject, dict[str, Any]]:
    staging = environment.staging
    clear_staging(staging)
    stored, path = await _download(storage, staging)
    if not config.passphrase:
        raise BackupError("Не задан пароль шифрования")
    extracted = staging / _EXTRACT_DIR
    await decrypt_to_directory(path, extracted, passphrase=config.passphrase)
    path.unlink()
    directory = _bundle_directory(extracted)
    checked_files = await asyncio.to_thread(check_checksums, directory)
    manifest = json.loads((directory / MANIFEST_NAME).read_text())
    components = await asyncio.to_thread(check_archives, directory, manifest)
    database = manifest["database"]
    async with TemporaryPostgres(
        environment,
        user=database["user"],
        database=database["name"],
    ) as postgres:
        await postgres.load(
            directory / database["file"],
            staging,
            after_restore=_after_restore_sql(directory),
        )
        rows = await compare_database(postgres, database)
    return stored, {
        "tracker_commit": manifest["tracker_commit"],
        "created_at": manifest["created_at"],
        "alembic_version": database["alembic_version"],
        "checksums": checked_files,
        "components": components,
        "tables": len(database["table_counts"]),
        "rows": rows,
    }


async def run_verify(
    db_session: AsyncSession,
    redis_client: Redis,
    *,
    config: BackupConfig,
    storage: S3Storage,
    environment: VerifyEnvironment,
) -> BackupRun:
    """Проверяет последнюю копию; сбой — `BackupError` и уведомление администраторам."""
    run = await start_run(db_session, kind=BackupRunKind.VERIFY)
    try:
        async with backup_lock(redis_client, wait_seconds=environment.lock_wait_seconds):
            await close_interrupted_runs(db_session, current=run)
            try:
                stored, details = await _verify(
                    config=config,
                    storage=storage,
                    environment=environment,
                )
            finally:
                clear_staging(environment.staging)
    except Exception as exc:  # noqa: BLE001 — любой сбой закрывает запуск и уведомляет администраторов
        message = failure_message(exc)
        await fail_run(
            db_session,
            run,
            message=message,
            event=NotificationEvent.BACKUP_VERIFY_FAILED,
        )
        raise BackupError(message) from exc
    await finish_run(
        db_session,
        run,
        status=BackupRunStatus.SUCCESS,
        object_key=stored.key,
        size_bytes=stored.size,
        sha256=stored.sha256,
        details=details,
    )
    logger.info("backup_verified", object_key=stored.key, rows=details["rows"])
    return run
