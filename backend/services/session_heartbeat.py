"""
Пульс в Redis показывает, что воркер держит сессию (раздел 6.6 ТЗ).
Блокировка PostgreSQL обеспечивает единственного владельца (раздел 17.4).

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
from contextvars import ContextVar
from dataclasses import dataclass
from hashlib import blake2b
from typing import TYPE_CHECKING

from redis.exceptions import RedisError
from sqlalchemy import text

from app_logging.config import get_logger
from db.session import engine
from services.session_timing import HEARTBEAT_INTERVAL_SECONDS, HEARTBEAT_TTL_SECONDS

if TYPE_CHECKING:
    from redis.asyncio import Redis

logger = get_logger("session_heartbeat")

# Продолжение после `clear_context` ставится, пока предыдущий таск ещё
# держит сессию: он отпускает её через мгновения.
SESSION_OWNER_WAIT_SECONDS = 30.0
_ACQUIRE_POLL_SECONDS = 0.5
_RELEASE_TIMEOUT_SECONDS = 2.0

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


class SessionOwnershipLostError(asyncio.CancelledError):
    """Старый владелец должен завершить ход без перевода задачи в failed."""


@dataclass(slots=True)
class _SessionLease:
    redis_client: Redis
    task_id: uuid.UUID
    token: str
    renewed_at: float


_current_lease: ContextVar[_SessionLease | None] = ContextVar("session_lease", default=None)


async def require_session_owner() -> None:
    """Проверка перед началом работы, без ожидания очередного обновления пульса."""
    lease = _current_lease.get()
    if lease is None:
        return
    loop = asyncio.get_running_loop()
    while True:
        remaining = lease.renewed_at + HEARTBEAT_TTL_SECONDS - loop.time()
        if remaining <= 0:
            raise SessionOwnershipLostError
        try:
            async with asyncio.timeout(remaining):
                value = await lease.redis_client.get(_heartbeat_key(lease.task_id))
        except RedisError as exc:
            if loop.time() >= lease.renewed_at + HEARTBEAT_TTL_SECONDS:
                raise SessionOwnershipLostError from exc
            await asyncio.sleep(min(_ACQUIRE_POLL_SECONDS, remaining))
            continue
        except TimeoutError as exc:
            raise SessionOwnershipLostError from exc
        if value not in (lease.token, lease.token.encode()):
            raise SessionOwnershipLostError
        return


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
    lease: _SessionLease, interval: float, owner: asyncio.Task[object], lost_marker: object
) -> None:
    loop = asyncio.get_running_loop()
    failures = 0
    while True:
        await asyncio.sleep(
            min(interval, max(0, lease.renewed_at + HEARTBEAT_TTL_SECONDS - loop.time()))
        )
        deadline = lease.renewed_at + HEARTBEAT_TTL_SECONDS
        if loop.time() >= deadline:
            reason = "deadline"
            break
        try:
            async with asyncio.timeout_at(deadline):
                renewed = await _renew(lease.redis_client, lease.task_id, lease.token)
        except RedisError:
            failures += 1
            if failures == 1:
                logger.warning("session_heartbeat_degraded", task_id=str(lease.task_id))
            continue
        except TimeoutError:
            reason = "deadline"
            break
        if not renewed:
            reason = "token_lost"
            break
        lease.renewed_at = loop.time()
        if failures:
            logger.info(
                "session_heartbeat_recovered", task_id=str(lease.task_id), failures=failures
            )
            failures = 0

    logger.warning(
        "session_heartbeat_ownership_lost",
        task_id=str(lease.task_id),
        reason=reason,
        failures=failures,
    )
    owner.cancel(lost_marker)


@asynccontextmanager
async def _hold_session_lock(task_id: uuid.UUID, *, wait_seconds: float) -> AsyncIterator[None]:
    """Блокировка на отдельном соединении переживает потерю ключа Redis."""
    lock_id = int.from_bytes(
        blake2b(task_id.bytes, digest_size=8, person=b"tracker-session").digest(),
        "big",
        signed=True,
    )
    loop = asyncio.get_running_loop()
    deadline = loop.time() + wait_seconds
    async with engine.connect() as connection:
        try:
            while True:
                acquired = await connection.scalar(
                    text("SELECT pg_try_advisory_lock(:key)"), {"key": lock_id}
                )
                await connection.commit()
                if acquired:
                    break
                if loop.time() >= deadline:
                    raise SessionAlreadyOwnedError(
                        f"Сессию задачи {task_id} держит другой исполнитель"
                    )
                await asyncio.sleep(min(_ACQUIRE_POLL_SECONDS, deadline - loop.time()))
            try:
                yield
            finally:
                await connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": lock_id})
                await connection.commit()
        except SessionAlreadyOwnedError:
            raise
        except BaseException:
            # При обрыве или отмене соединение с блокировкой нельзя вернуть в пул.
            await connection.invalidate()
            raise


@asynccontextmanager
async def keep_session_heartbeat(
    redis_client: Redis,
    task_id: uuid.UUID,
    *,
    interval: float = HEARTBEAT_INTERVAL_SECONDS,
    acquire_timeout: float = 0.0,
) -> AsyncIterator[None]:
    """Владение сессией в PostgreSQL и пульс в Redis на всё время работы."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + acquire_timeout
    async with _hold_session_lock(task_id, wait_seconds=acquire_timeout):
        async with _publish_session_heartbeat(
            redis_client, task_id, interval=interval, wait_seconds=max(0, deadline - loop.time())
        ):
            yield


@asynccontextmanager
async def _publish_session_heartbeat(
    redis_client: Redis, task_id: uuid.UUID, *, interval: float, wait_seconds: float
) -> AsyncIterator[None]:
    token = uuid.uuid4().hex
    if not await _acquire(redis_client, task_id, token, wait_seconds=wait_seconds):
        raise SessionAlreadyOwnedError(f"Сессию задачи {task_id} держит другой исполнитель")
    owner = asyncio.current_task()
    assert owner is not None
    lease = _SessionLease(redis_client, task_id, token, asyncio.get_running_loop().time())
    lease_token = _current_lease.set(lease)
    lost_marker = object()
    beating = asyncio.create_task(_keep_beating(lease, interval, owner, lost_marker))
    try:
        yield
    except SessionOwnershipLostError:
        logger.warning("session_owner_stopped", task_id=str(task_id))
    except asyncio.CancelledError as exc:
        if exc.args != (lost_marker,):
            raise
        owner.uncancel()
        if owner.cancelling():
            raise
        logger.warning("session_owner_stopped", task_id=str(task_id))
    finally:
        _current_lease.reset(lease_token)
        beating.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await beating
        # При недоступном Redis ключ истечёт сам. Блокировка PostgreSQL
        # должна освободиться и в этом случае.
        try:
            async with asyncio.timeout(_RELEASE_TIMEOUT_SECONDS):
                await _release(redis_client, task_id, token)
        except (RedisError, TimeoutError):
            logger.warning("session_heartbeat_release_deferred", task_id=str(task_id))
