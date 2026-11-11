"""
Каталог копии (раздел 20.4 ТЗ) — то, что после расшифровки принимает
`install.sh --restore`: `.env`, дамп `tracker-<UTC>.sql.gz`, `<volume>.tar.gz`,
`after-restore.sql`, а также `manifest.json`, `SHA256SUMS`, `restore.sh` и
`RESTORE.md`.

Дамп снимается во время запуска бэкапа, поэтому в нём этот запуск и
периодическая задача `backup_to_s3` ещё «выполняются». `after-restore.sql`
(его выполняют `install.sh --restore` и еженедельная проверка сразу после
дампа) записывает им итог самой копии — иначе восстановленный сервер
показывал бы бэкап незавершённым до следующего запуска.

`manifest.json` описывает копию: коммит трекера, на котором она снята
(`restore.sh` ставит именно его), версию схемы и число строк каждой таблицы
(их сверяет еженедельная проверка), состав и пропущенные файлы.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app_logging.config import get_logger
from services.backup.archive import ArchiveOptions, SkippedFile, archive_directory
from services.backup.components import COMPONENTS, ENV_FILE_RELATIVE, Component
from services.backup.dump import DumpCommandFactory, dump_database
from services.backup.files import sha256_file

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

    from services.backup.settings import BackupConfig

logger = get_logger("backup_bundle")

MANIFEST_FORMAT_VERSION = 1
MANIFEST_NAME = "manifest.json"
CHECKSUMS_NAME = "SHA256SUMS"
RESTORE_SCRIPT_NAME = "restore.sh"
RESTORE_GUIDE_NAME = "RESTORE.md"
AFTER_RESTORE_SQL_NAME = "after-restore.sql"
# Имя периодической задачи бэкапа — `tasks/celery_app.BACKUP_TO_S3` (тест сверяет).
BACKUP_PERIODIC_TASK = "backup_to_s3"
ENV_NAME = ".env"
BUNDLE_PREFIX = "tracker-backup-"
TIMESTAMP_FORMAT = "%Y%m%dT%H%M%SZ"
GIT_SHA_ENV = "GIT_SHA"
_UNKNOWN_COMMIT = "unknown"
_TEMPLATES_DIR = Path(__file__).with_name("templates")
_SECRET_FILE_MODE = 0o600
_SCRIPT_MODE = 0o755


class BundleError(Exception):
    """Копию не собрать: нет обязательного источника данных."""


@dataclass(frozen=True, slots=True)
class BundleSources:
    # Корень, где у backup-worker смонтированы volume (`<корень>/<имя>`).
    root: Path
    env_file: Path

    @classmethod
    def at(cls, root: Path) -> BundleSources:
        return cls(root=root, env_file=root / ENV_FILE_RELATIVE)

    def component_dir(self, component: Component) -> Path:
        return self.root / component.name


@dataclass(slots=True)
class BundleResult:
    directory: Path
    manifest: dict[str, Any]
    skipped: list[SkippedFile] = field(default_factory=list)


def bundle_name(started_at: datetime) -> str:
    return f"{BUNDLE_PREFIX}{started_at.strftime(TIMESTAMP_FORMAT)}"


def restore_script() -> str:
    return (_TEMPLATES_DIR / RESTORE_SCRIPT_NAME).read_text()


def restore_guide(config: BackupConfig) -> str:
    """Инструкция с адресом хранилища; ключи и пароль в неё не попадают."""
    text = (_TEMPLATES_DIR / RESTORE_GUIDE_NAME).read_text()
    for placeholder, value in (
        ("@ENDPOINT@", config.endpoint or ""),
        ("@REGION@", config.region or ""),
        ("@BUCKET@", config.bucket or ""),
        ("@FOLDER@", config.folder),
    ):
        text = text.replace(placeholder, value)
    return text


def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def after_restore_sql(
    *,
    run_id: uuid.UUID,
    object_key: str,
    skipped: list[SkippedFile],
    finished_at: datetime,
) -> str:
    """
    Итог запуска, во время которого снята копия. Только из `running`:
    повторное выполнение и дамп, где запуска нет, ничего не меняют. Таблицы —
    со схемой: plain-дамп `pg_dump` очищает `search_path`.
    """
    status = "warning" if skipped else "success"
    skipped_json = json.dumps([item.as_dict() for item in skipped], ensure_ascii=False)
    finished = _sql_literal(finished_at.isoformat())
    return (
        "-- Копия снята во время этого запуска: в дампе он ещё выполняется.\n"
        f"UPDATE public.backup_runs SET status = {_sql_literal(status)}, finished_at = {finished}, "
        f"object_key = {_sql_literal(object_key)}, skipped_files = {_sql_literal(skipped_json)}"
        f" WHERE id = {_sql_literal(str(run_id))} AND status = 'running';\n"
        "UPDATE public.periodic_tasks SET last_run_status = 'success', "
        f"last_run_at = {finished} WHERE name = {_sql_literal(BACKUP_PERIODIC_TASK)}"
        " AND last_run_status = 'running';\n"
    )


def tracker_commit() -> str:
    return os.environ.get(GIT_SHA_ENV) or _UNKNOWN_COMMIT


def _file_entry(path: Path) -> dict[str, Any]:
    return {"file": path.name, "size": path.stat().st_size, "sha256": sha256_file(path)}


async def _archive_components(
    sources: BundleSources,
    directory: Path,
    *,
    options: ArchiveOptions,
) -> tuple[list[dict[str, Any]], list[SkippedFile]]:
    entries: list[dict[str, Any]] = []
    skipped: list[SkippedFile] = []
    for component in COMPONENTS:
        source = sources.component_dir(component)
        if not source.is_dir():
            if component.required:
                raise BundleError(f"Нет данных {component.name}: {source} не подключён")
            entries.append({"name": component.name, "present": False})
            continue
        target = directory / component.archive_name
        stats = await asyncio.to_thread(
            archive_directory,
            source,
            target,
            component=component.name,
            options=ArchiveOptions(
                excludes=component.all_excludes,
                attempts=options.attempts,
                retry_delay_seconds=options.retry_delay_seconds,
                spool_dir=options.spool_dir,
            ),
        )
        skipped.extend(stats.skipped)
        entries.append(
            {
                "name": component.name,
                "present": True,
                "files": stats.files,
                "bytes": stats.bytes,
                **await asyncio.to_thread(_file_entry, target),
            },
        )
    return entries, skipped


def _write_checksums(directory: Path) -> None:
    lines = [
        f"{sha256_file(path)}  {path.name}"
        for path in sorted(directory.iterdir())
        if path.is_file() and path.name != CHECKSUMS_NAME
    ]
    (directory / CHECKSUMS_NAME).write_text("\n".join(lines) + "\n")


def _copy_env(sources: BundleSources, directory: Path) -> None:
    if not sources.env_file.is_file():
        raise BundleError(f"Нет .env сервера: {sources.env_file} не подключён")
    target = directory / ENV_NAME
    shutil.copyfile(sources.env_file, target)
    target.chmod(_SECRET_FILE_MODE)


@dataclass(frozen=True, slots=True)
class BundleRequest:
    staging: Path
    started_at: datetime
    sources: BundleSources
    config: BackupConfig
    archive_options: ArchiveOptions
    # Запуск бэкапа и ключ копии в S3 — для `after-restore.sql`.
    run_id: uuid.UUID
    object_key: str


async def build_bundle(
    request: BundleRequest,
    *,
    engine: AsyncEngine,
    dump_command: DumpCommandFactory,
) -> BundleResult:
    """Собирает каталог копии в `staging/<имя копии>/`."""
    directory = request.staging / bundle_name(request.started_at)
    directory.mkdir(parents=True)
    _copy_env(request.sources, directory)
    dump_path = directory / f"tracker-{request.started_at.strftime(TIMESTAMP_FORMAT)}.sql.gz"
    dump = await dump_database(engine, dump_path, command_factory=dump_command)
    components, skipped = await _archive_components(
        request.sources,
        directory,
        options=request.archive_options,
    )
    (directory / AFTER_RESTORE_SQL_NAME).write_text(
        after_restore_sql(
            run_id=request.run_id,
            object_key=request.object_key,
            skipped=skipped,
            finished_at=datetime.now(UTC),
        ),
    )
    script = directory / RESTORE_SCRIPT_NAME
    script.write_text(restore_script())
    script.chmod(_SCRIPT_MODE)
    (directory / RESTORE_GUIDE_NAME).write_text(restore_guide(request.config))
    manifest: dict[str, Any] = {
        "format_version": MANIFEST_FORMAT_VERSION,
        "created_at": request.started_at.isoformat(),
        "tracker_commit": tracker_commit(),
        "database": {
            "name": dump.database,
            "user": dump.user,
            "alembic_version": dump.alembic_version,
            "table_counts": dump.table_counts,
            **await asyncio.to_thread(_file_entry, dump_path),
        },
        "components": components,
        "skipped_files": [item.as_dict() for item in skipped],
    }
    (directory / MANIFEST_NAME).write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    await asyncio.to_thread(_write_checksums, directory)
    logger.info("backup_bundle_built", components=len(components), skipped=len(skipped))
    return BundleResult(directory=directory, manifest=manifest, skipped=skipped)
