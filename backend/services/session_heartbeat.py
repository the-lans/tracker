"""
Пульс сессии задачи (раздел 6.6 ТЗ): признак того, что воркер всё ещё
держит сессию Claude Code.

Периодическая задача `check_remote_control_bridges` работает в другом
процессе и не видит процесс CLI — она видит только этот ключ Redis. Пока
воркер жив, фоновая задача обновляет ключ чаще, чем истекает его TTL.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from redis.exceptions import RedisError

from app_logging.config import get_logger

if TYPE_CHECKING:
    import uuid

    from redis.asyncio import Redis

logger = get_logger("session_heartbeat")

HEARTBEAT_INTERVAL_SECONDS = 30.0
# Три пропущенных обновления подряд — воркера больше нет.
HEARTBEAT_TTL_SECONDS = 90


def _heartbeat_key(task_id: uuid.UUID) -> str:
    return f"task:{task_id}:session-alive"


async def beat(redis_client: Redis, task_id: uuid.UUID) -> None:
    await redis_client.set(_heartbeat_key(task_id), "1", ex=HEARTBEAT_TTL_SECONDS)


async def is_session_alive(redis_client: Redis, task_id: uuid.UUID) -> bool:
    return bool(await redis_client.exists(_heartbeat_key(task_id)))


async def _keep_beating(redis_client: Redis, task_id: uuid.UUID, interval: float) -> None:
    while True:
        await asyncio.sleep(interval)
        try:
            await beat(redis_client, task_id)
        except RedisError:
            # Пропуск одного обновления не страшен: TTL покрывает три интервала.
            logger.warning("session_heartbeat_failed", task_id=str(task_id))


@asynccontextmanager
async def keep_session_heartbeat(
    redis_client: Redis,
    task_id: uuid.UUID,
    *,
    interval: float = HEARTBEAT_INTERVAL_SECONDS,
) -> AsyncIterator[None]:
    """Пульс на всё время, пока воркер держит сессию; по выходе ключ снимается."""
    await beat(redis_client, task_id)
    beating = asyncio.create_task(_keep_beating(redis_client, task_id, interval))
    try:
        yield
    finally:
        beating.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await beating
        with contextlib.suppress(RedisError):
            await redis_client.delete(_heartbeat_key(task_id))
