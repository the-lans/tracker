"""
Пульс сессии задачи (раздел 6.6 ТЗ): признак того, что воркер всё ещё
держит сессию Claude Code, — и блокировка её владельца (раздел 17.4).

Периодическая задача `check_remote_control_bridges` работает в другом
процессе и не видит процесс CLI — она видит только этот ключ Redis. Пока
воркер жив, фоновая задача обновляет ключ чаще, чем истекает его TTL.

Ключ ставится `SET NX` со случайным токеном владельца: второй исполнитель
той же задачи (повторная доставка Celery, двойное продолжение после
`clear_context`) ждёт освобождения ограниченное время и уходит без эффектов.
Продлевает и снимает ключ только владелец — сравнение токена в Lua-скрипте.
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from redis.exceptions import RedisError

from app_logging.config import get_logger

if TYPE_CHECKING:
    from redis.asyncio import Redis

logger = get_logger("session_heartbeat")

HEARTBEAT_INTERVAL_SECONDS = 30.0
# Три пропущенных обновления подряд — воркера больше нет.
HEARTBEAT_TTL_SECONDS = 90
# Продолжение после `clear_context` ставится, пока предыдущий таск ещё
# держит сессию: он отпускает её через мгновения.
SESSION_OWNER_WAIT_SECONDS = 30.0
_ACQUIRE_POLL_SECONDS = 0.5

_RENEW_IF_OWNER = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('expire', KEYS[1], ARGV[2])
end
return 0
"""
_RELEASE_IF_OWNER = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
end
return 0
"""


class SessionAlreadyOwnedError(RuntimeError):
    """Сессию задачи держит другой исполнитель."""


def _heartbeat_key(task_id: uuid.UUID) -> str:
    return f"task:{task_id}:session-alive"


async def beat(redis_client: Redis, task_id: uuid.UUID) -> None:
    """Пульс без владельца — для проверок со стороны (тесты, диагностика)."""
    await redis_client.set(_heartbeat_key(task_id), "1", ex=HEARTBEAT_TTL_SECONDS)


async def is_session_alive(redis_client: Redis, task_id: uuid.UUID) -> bool:
    return bool(await redis_client.exists(_heartbeat_key(task_id)))


async def _acquire(
    redis_client: Redis, task_id: uuid.UUID, token: str, *, wait_seconds: float
) -> bool:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + wait_seconds
    while True:
        if await redis_client.set(
            _heartbeat_key(task_id), token, nx=True, ex=HEARTBEAT_TTL_SECONDS
        ):
            return True
        if loop.time() >= deadline:
            return False
        await asyncio.sleep(_ACQUIRE_POLL_SECONDS)


async def _renew(redis_client: Redis, task_id: uuid.UUID, token: str) -> bool:
    renewed = await redis_client.eval(
        _RENEW_IF_OWNER,
        1,
        _heartbeat_key(task_id),
        token,
        HEARTBEAT_TTL_SECONDS,
    )
    return bool(renewed)


async def _release(redis_client: Redis, task_id: uuid.UUID, token: str) -> None:
    await redis_client.eval(_RELEASE_IF_OWNER, 1, _heartbeat_key(task_id), token)


async def _keep_beating(
    redis_client: Redis, task_id: uuid.UUID, token: str, interval: float
) -> None:
    while True:
        await asyncio.sleep(interval)
        try:
            if not await _renew(redis_client, task_id, token):
                logger.warning("session_heartbeat_ownership_lost", task_id=str(task_id))
        except RedisError:
            # Пропуск одного обновления не страшен: TTL покрывает три интервала.
            logger.warning("session_heartbeat_failed", task_id=str(task_id))


@asynccontextmanager
async def keep_session_heartbeat(
    redis_client: Redis,
    task_id: uuid.UUID,
    *,
    interval: float = HEARTBEAT_INTERVAL_SECONDS,
    acquire_timeout: float = 0.0,
) -> AsyncIterator[None]:
    """
    Пульс и владение сессией на всё время, пока воркер её держит; по выходе
    ключ снимается. Сессию держит другой — `SessionAlreadyOwnedError` после
    ``acquire_timeout`` секунд ожидания.
    """
    token = uuid.uuid4().hex
    if not await _acquire(redis_client, task_id, token, wait_seconds=acquire_timeout):
        raise SessionAlreadyOwnedError(f"Сессию задачи {task_id} держит другой исполнитель")
    beating = asyncio.create_task(_keep_beating(redis_client, task_id, token, interval))
    try:
        yield
    finally:
        beating.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await beating
        with contextlib.suppress(RedisError):
            await _release(redis_client, task_id, token)
