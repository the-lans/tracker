"""
Распределённая блокировка Redis `SET NX` + TTL (раздел 17.4, 17.5 ТЗ).

Для операций, критичных к повторному выполнению: пуш в Git и обработка
очереди ручных запросов (раздел 17.5:
"Обработка очереди task_manual_request_queue обязана быть защищена той же
распределённой блокировкой, что и обращения к сессии"). Повтор
push-уведомления исключается иначе — однократным изменением состояния или
ключом `SET NX` с TTL у самого события (раздел 17.4).
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from app_logging.config import get_logger

if TYPE_CHECKING:
    from redis.asyncio import Redis

logger = get_logger("distributed_lock")

DEFAULT_LOCK_TTL_SECONDS = 60
_LOCK_POLL_SECONDS = 0.05


class LockNotAcquiredError(Exception):
    """Операция уже выполняется другим процессом — блокировка занята."""


def lock_key(task_id: uuid.UUID, operation: str) -> str:
    return f"lock:{task_id}:{operation}"


@asynccontextmanager
async def acquire_lock(
    redis_client: Redis,
    key: str,
    *,
    ttl_seconds: int = DEFAULT_LOCK_TTL_SECONDS,
    busy_message: str,
) -> AsyncIterator[None]:
    """`SET NX` с TTL; поднимает `LockNotAcquiredError(busy_message)`, если уже занята.

    Освобождение сверяет токен — если TTL истёк и блокировку успел
    перехватить кто-то другой, чужой захват не удаляется по ошибке.
    """
    token = str(uuid.uuid4())
    acquired = await redis_client.set(key, token, nx=True, ex=ttl_seconds)
    if not acquired:
        raise LockNotAcquiredError(busy_message)
    logger.info("distributed_lock_acquired", key=key)
    try:
        yield
    finally:
        await _release(redis_client, key, token)
        logger.info("distributed_lock_released", key=key)


async def _release(redis_client: Redis, key: str, token: str) -> None:
    current = await redis_client.get(key)
    current_token = current.decode() if isinstance(current, bytes) else current
    if current_token == token:
        await redis_client.delete(key)


@asynccontextmanager
async def wait_for_lock(
    redis_client: Redis,
    key: str,
    *,
    ttl_seconds: int,
    wait_seconds: float,
) -> AsyncIterator[bool]:
    """
    `SET NX` с TTL и коротким ожиданием занятой блокировки. Отдаёт, захвачена
    ли она: по истечении ожидания вызывающий код решает сам, идти ли без неё.
    """
    token = str(uuid.uuid4())
    deadline = asyncio.get_running_loop().time() + wait_seconds
    while not await redis_client.set(key, token, nx=True, ex=ttl_seconds):
        if asyncio.get_running_loop().time() >= deadline:
            logger.warning("distributed_lock_wait_expired", key=key)
            yield False
            return
        await asyncio.sleep(_LOCK_POLL_SECONDS)
    try:
        yield True
    finally:
        await _release(redis_client, key, token)


@asynccontextmanager
async def acquire_task_operation_lock(
    redis_client: Redis,
    *,
    task_id: uuid.UUID,
    operation: str,
    ttl_seconds: int = DEFAULT_LOCK_TTL_SECONDS,
) -> AsyncIterator[None]:
    """Блокировка операции над задачей (`lock:<task_id>:<operation>`)."""
    async with acquire_lock(
        redis_client,
        lock_key(task_id, operation),
        ttl_seconds=ttl_seconds,
        busy_message=f"Операция {operation!r} для задачи {task_id} уже выполняется",
    ):
        yield
