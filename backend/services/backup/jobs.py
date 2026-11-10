"""
Запуск бэкапа и проверки из периодических задач (раздел 16.2 ТЗ):
настройки из `system_settings`, хранилище, пути `backup-worker`.
Выключено или не настроено — выход без действий и без ошибки.
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from app_logging.config import get_logger
from db.session import engine
from services.backup.archive import ArchiveOptions
from services.backup.bundle import BundleSources
from services.backup.components import source_root
from services.backup.dump import pg_dump_command
from services.backup.runner import BackupEnvironment, run_backup
from services.backup.settings import BackupConfig, load_backup_config
from services.backup.storage import S3Storage
from services.backup.verify import VerifyEnvironment, run_verify
from services.redis_connection import redis_connection

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger("backup_jobs")

STAGING_DIR_ENV = "BACKUP_STAGING_DIR"
DEFAULT_STAGING_DIR = Path("/data/backup-staging")


def staging_dir() -> Path:
    return Path(os.environ.get(STAGING_DIR_ENV, str(DEFAULT_STAGING_DIR)))


async def _ready_config(db_session: AsyncSession, job: str) -> BackupConfig | None:
    config = await load_backup_config(db_session)
    if not (config.enabled and config.is_complete):
        logger.info("backup_not_configured", job=job, enabled=config.enabled)
        return None
    return config


async def backup_job(db_session: AsyncSession, *, now: datetime) -> None:
    config = await _ready_config(db_session, "backup")
    if config is None:
        return
    staging = staging_dir()
    environment = BackupEnvironment(
        staging=staging,
        sources=BundleSources.at(source_root()),
        engine=engine,
        dump_command=pg_dump_command(engine.url),
        archive_options=ArchiveOptions(spool_dir=staging),
    )
    async with redis_connection() as redis_client:
        await run_backup(
            db_session,
            redis_client,
            config=config,
            storage=S3Storage.from_config(config),
            environment=environment,
            started_at=now,
        )


async def verify_job(db_session: AsyncSession) -> None:
    config = await _ready_config(db_session, "verify")
    if config is None:
        return
    async with redis_connection() as redis_client:
        await run_verify(
            db_session,
            redis_client,
            config=config,
            storage=S3Storage.from_config(config),
            environment=VerifyEnvironment(staging=staging_dir()),
        )
