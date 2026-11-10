"""
Ежедневный бэкап в S3 (`backup_to_s3`, раздел 20.4 ТЗ).

Порядок: блокировка → проверка свободного места → каталог копии (дамп,
архивы volume, `.env`, manifest) → шифрование → загрузка → проверка
загруженного объекта (размер и SHA-256) → инструкция и скрипт
восстановления рядом в папке → удаление копий сверх `retention_count`.
Старые копии удаляются только после того, как новая загружена и проверена:
сбой на любом шаге оставляет хранилище как было. Промежуточные файлы
удаляются в любом случае.
"""

from __future__ import annotations

import asyncio
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app_logging.app_logs import write_app_log
from app_logging.config import get_logger
from db.models.enums import AppLogLevel, BackupRunKind, BackupRunStatus
from services.backup.archive import ArchiveOptions
from services.backup.bundle import (
    RESTORE_GUIDE_NAME,
    RESTORE_SCRIPT_NAME,
    BundleRequest,
    BundleSources,
    build_bundle,
    bundle_name,
    restore_guide,
    restore_script,
)
from services.backup.components import COMPONENTS
from services.backup.crypto_gpg import encrypt_directory
from services.backup.dump import DumpCommandFactory
from services.backup.files import sha256_file, tree_size
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
from services.backup.storage import BACKUP_SUFFIX, S3Storage
from services.notifications import NotificationEvent

if TYPE_CHECKING:
    import uuid

    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

    from db.models.backups import BackupRun
    from services.backup.settings import BackupConfig

logger = get_logger("backup_runner")

# Архивы ≈ данные, зашифрованная копия ≈ архивы: нужно вдвое больше данных
# и запас на временные файлы чтения.
SPACE_FACTOR = 2.2
_MEBIBYTE = 1024 * 1024
SPACE_MARGIN_BYTES = 512 * _MEBIBYTE
_MARKDOWN_TYPE = "text/markdown; charset=utf-8"
_SHELL_TYPE = "text/x-shellscript; charset=utf-8"
_APP_LOG_SOURCE = "backup.s3"


@dataclass(frozen=True, slots=True)
class BackupEnvironment:
    """Где брать данные и где собирать копию; в тестах — свои пути и команда дампа."""

    staging: Path
    sources: BundleSources
    engine: AsyncEngine
    dump_command: DumpCommandFactory
    archive_options: ArchiveOptions
    lock_wait_seconds: float = BACKUP_LOCK_WAIT_SECONDS


def clear_staging(staging: Path) -> None:
    """Остатки прерванного запуска: под блокировкой staging никто больше не трогает."""
    staging.mkdir(parents=True, exist_ok=True)
    for child in staging.iterdir():
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child, ignore_errors=True)
        else:
            child.unlink(missing_ok=True)


def required_space(sources: BundleSources) -> int:
    data = sum(
        tree_size(sources.component_dir(component))
        for component in COMPONENTS
        if sources.component_dir(component).is_dir()
    )
    return int(data * SPACE_FACTOR) + SPACE_MARGIN_BYTES


def ensure_space(staging: Path, required: int) -> None:
    free = shutil.disk_usage(staging).free
    if free < required:
        raise BackupError(
            f"Недостаточно места для копии: нужно {required // _MEBIBYTE} МиБ, "
            f"свободно {free // _MEBIBYTE} МиБ",
        )


async def verify_upload(storage: S3Storage, name: str, *, size: int, sha256: str) -> None:
    stored = await storage.head(name)
    if stored is None:
        raise BackupError("Загруженная копия не найдена в хранилище")
    if stored.size != size or stored.sha256 != sha256:
        raise BackupError("Загруженная копия не совпадает с локальной (размер или SHA-256)")


async def rotate(storage: S3Storage, *, keep: int, current: str) -> list[str]:
    """Удаляет самые старые копии сверх `keep`; только что загруженную — никогда."""
    names = [storage.name_of(stored) for stored in await storage.list_backups()]
    if current not in names:
        names.append(current)
        names.sort()
    excess = names[: max(len(names) - keep, 0)]
    deleted = []
    for name in excess:
        if name == current:
            continue
        await storage.delete(name)
        deleted.append(name)
    if deleted:
        logger.info("backup_rotated", deleted=len(deleted), kept=keep)
    return deleted


async def _upload_guides(storage: S3Storage, config: BackupConfig) -> None:
    await storage.put_text(RESTORE_GUIDE_NAME, restore_guide(config), content_type=_MARKDOWN_TYPE)
    await storage.put_text(RESTORE_SCRIPT_NAME, restore_script(), content_type=_SHELL_TYPE)


@dataclass(frozen=True, slots=True)
class _Uploaded:
    name: str
    size: int
    sha256: str
    manifest: dict[str, Any]


async def _make_and_upload(
    *,
    config: BackupConfig,
    storage: S3Storage,
    environment: BackupEnvironment,
    started_at: datetime,
    run_id: uuid.UUID,
) -> _Uploaded:
    staging = environment.staging
    name = bundle_name(started_at) + BACKUP_SUFFIX
    clear_staging(staging)
    ensure_space(staging, await asyncio.to_thread(required_space, environment.sources))
    await storage.ensure_folder()
    bundle = await build_bundle(
        BundleRequest(
            staging=staging,
            started_at=started_at,
            sources=environment.sources,
            config=config,
            archive_options=environment.archive_options,
            run_id=run_id,
            object_key=storage.key(name),
        ),
        engine=environment.engine,
        dump_command=environment.dump_command,
    )
    encrypted = staging / name
    if not config.passphrase:
        raise BackupError("Не задан пароль шифрования")
    await encrypt_directory(bundle.directory, encrypted, passphrase=config.passphrase)
    shutil.rmtree(bundle.directory)
    size = encrypted.stat().st_size
    digest = await asyncio.to_thread(sha256_file, encrypted)
    await storage.upload(encrypted, name, sha256=digest)
    await verify_upload(storage, name, size=size, sha256=digest)
    await _upload_guides(storage, config)
    return _Uploaded(name=name, size=size, sha256=digest, manifest=bundle.manifest)


def _details(manifest: dict[str, Any], deleted: list[str]) -> dict[str, Any]:
    return {
        "tracker_commit": manifest["tracker_commit"],
        "alembic_version": manifest["database"]["alembic_version"],
        "tables": len(manifest["database"]["table_counts"]),
        "components": manifest["components"],
        "rotated": deleted,
    }


async def run_backup(
    db_session: AsyncSession,
    redis_client: Redis,
    *,
    config: BackupConfig,
    storage: S3Storage,
    environment: BackupEnvironment,
    started_at: datetime,
) -> BackupRun:
    """Снимает и загружает копию; сбой — `BackupError` и уведомление администраторам."""
    run = await start_run(db_session, kind=BackupRunKind.BACKUP)
    try:
        async with backup_lock(redis_client, wait_seconds=environment.lock_wait_seconds):
            await close_interrupted_runs(db_session, current=run)
            try:
                uploaded = await _make_and_upload(
                    config=config,
                    storage=storage,
                    environment=environment,
                    started_at=started_at,
                    run_id=run.id,
                )
                deleted = await rotate(storage, keep=config.retention_count, current=uploaded.name)
            finally:
                clear_staging(environment.staging)
    except Exception as exc:  # noqa: BLE001 — любой сбой закрывает запуск и уведомляет администраторов
        message = failure_message(exc)
        await fail_run(db_session, run, message=message, event=NotificationEvent.BACKUP_FAILED)
        raise BackupError(message) from exc
    skipped = uploaded.manifest["skipped_files"]
    status = BackupRunStatus.WARNING if skipped else BackupRunStatus.SUCCESS
    await finish_run(
        db_session,
        run,
        status=status,
        object_key=storage.key(uploaded.name),
        size_bytes=uploaded.size,
        sha256=uploaded.sha256,
        skipped_files=skipped,
        details=_details(uploaded.manifest, deleted),
    )
    if skipped:
        await write_app_log(
            level=AppLogLevel.WARNING,
            source=_APP_LOG_SOURCE,
            message=f"Копия загружена, пропущено файлов: {len(skipped)}",
            context={"object_key": storage.key(uploaded.name), "skipped": skipped[:50]},
        )
    logger.info("backup_uploaded", object_key=storage.key(uploaded.name), size=uploaded.size)
    return run
