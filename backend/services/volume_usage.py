"""
Место на диске для страницы «Мониторинг» (раздел 15.5, 16.2 ТЗ).

Обход каталогов задач долгий, поэтому размеры volume считает периодическая
задача `measure_volume_usage` (сервис `worker`, где смонтированы все
volume) и кладёт в Redis; запрос страницы читает готовый замер. Размер базы —
`pg_database_size`, свободное место — у файловой системы каталога
репозиториев задач.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING

import sqlalchemy as sa
from pydantic import BaseModel, ValidationError
from redis.exceptions import RedisError

from app_logging.config import get_logger
from services.claude_config import resolve_sessions_root
from services.log_rotation import resolve_archive_root
from services.task_artifacts import resolve_user_files_root
from services.task_workspace import resolve_repos_root

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger("volume_usage")

VOLUME_USAGE_KEY = "monitoring:volume_usage"
# Замер раз в 15 минут; старше двух часов — задача не работает, показывать нечего.
VOLUME_USAGE_TTL = timedelta(hours=2)


class Volume(StrEnum):
    TASK_REPOS = "task_repos"
    USER_FILES = "user_files"
    CLAUDE_SESSIONS = "claude_sessions"
    LOG_ARCHIVE = "log_archive"


VOLUME_ROOTS: dict[Volume, Callable[[], Path]] = {
    Volume.TASK_REPOS: resolve_repos_root,
    Volume.USER_FILES: resolve_user_files_root,
    Volume.CLAUDE_SESSIONS: resolve_sessions_root,
    Volume.LOG_ARCHIVE: resolve_archive_root,
}


class VolumeSnapshot(BaseModel):
    measured_at: datetime
    # None — каталога нет в контейнере, где шёл замер.
    sizes: dict[Volume, int | None]


@dataclass(frozen=True, slots=True)
class DiskUsage:
    volumes: VolumeSnapshot | None
    database_bytes: int
    free_bytes: int | None
    total_bytes: int | None


def directory_size(root: Path) -> int | None:
    """Сумма размеров файлов без перехода по симлинкам; недоступное пропускается."""
    if not root.is_dir():
        return None
    total = 0
    pending = [str(root)]
    while pending:
        try:
            entries = list(os.scandir(pending.pop()))
        except OSError:
            continue
        for entry in entries:
            try:
                if entry.is_dir(follow_symlinks=False):
                    pending.append(entry.path)
                elif entry.is_file(follow_symlinks=False):
                    total += entry.stat(follow_symlinks=False).st_size
            except OSError:
                continue
    return total


def _measure() -> dict[Volume, int | None]:
    return {volume: directory_size(root()) for volume, root in VOLUME_ROOTS.items()}


async def store_volume_usage(redis_client: Redis, *, now: datetime) -> VolumeSnapshot:
    snapshot = VolumeSnapshot(measured_at=now, sizes=await asyncio.to_thread(_measure))
    await redis_client.set(
        VOLUME_USAGE_KEY,
        snapshot.model_dump_json(),
        ex=int(VOLUME_USAGE_TTL.total_seconds()),
    )
    return snapshot


async def read_volume_usage(redis_client: Redis) -> VolumeSnapshot | None:
    try:
        raw = await redis_client.get(VOLUME_USAGE_KEY)
    except RedisError:
        logger.warning("volume_usage_unavailable")
        return None
    if raw is None:
        return None
    try:
        return VolumeSnapshot.model_validate(json.loads(raw))
    except (ValueError, ValidationError):
        logger.warning("volume_usage_invalid")
        return None


def _filesystem_usage(path: Path) -> tuple[int, int] | None:
    try:
        usage = shutil.disk_usage(path)
    except OSError:
        return None
    return usage.free, usage.total


async def disk_usage(db_session: AsyncSession, redis_client: Redis) -> DiskUsage:
    database_bytes = await db_session.scalar(
        sa.select(sa.func.pg_database_size(sa.func.current_database())),
    )
    filesystem = _filesystem_usage(resolve_repos_root())
    return DiskUsage(
        volumes=await read_volume_usage(redis_client),
        database_bytes=int(database_bytes or 0),
        free_bytes=filesystem[0] if filesystem else None,
        total_bytes=filesystem[1] if filesystem else None,
    )
