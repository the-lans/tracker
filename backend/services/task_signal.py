"""Redis pub/sub-сигнализация между API и долгоживущим Celery-таском оркестратора.

Реализует "эквивалент asyncio.Event", о котором прямо говорит раздел 9.6 ТЗ:
голый ``asyncio.Event`` не работает между процессами (API-контейнер пишет в
`task_manual_request_queue`/`node_logs`, worker-контейнер, где реально
выполняется долгоживущая сессия, должен проснуться) — канал
``task:{task_id}:signal`` в Redis это тот самый эквивалент (см. план
реализации, "Архитектурные решения", п. B).

Сигнал не несёт полезной нагрузки: получатель обязан сам перечитать
состояние из БД (`node_logs`/`task_manual_request_queue`) после
пробуждения — канал лишь будит ожидающий цикл, не передаёт данные.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from redis.asyncio import Redis
from redis.asyncio.client import PubSub

from app_logging.config import get_logger

logger = get_logger("task_signal")

_POLL_SECONDS = 1.0


def channel_name(task_id: uuid.UUID) -> str:
    return f"task:{task_id}:signal"


async def publish_task_signal(redis_client: Redis, task_id: uuid.UUID) -> None:
    channel = channel_name(task_id)
    await redis_client.publish(channel, "1")
    logger.info("task_signal_published", task_id=str(task_id), channel=channel)


class TaskSignalSubscription:
    """
    Подписка на канал задачи. Сигнал, опубликованный после подписки, не
    теряется, даже если в этот момент подписчик ещё не ждёт: сначала
    подписаться, затем проверить состояние в БД, затем ждать.
    """

    def __init__(self, pubsub: PubSub, task_id: uuid.UUID) -> None:
        self._pubsub = pubsub
        self._task_id = task_id

    async def wait(self, *, timeout: float | None = None) -> bool:
        """
        ``True`` — сигнал получен, ``False`` — истёк ``timeout`` (`None` — ждать
        бессрочно).
        """
        loop = asyncio.get_running_loop()
        deadline = None if timeout is None else loop.time() + timeout
        while True:
            if deadline is not None:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    logger.info("task_signal_wait_timed_out", task_id=str(self._task_id))
                    return False
                poll_timeout = min(remaining, _POLL_SECONDS)
            else:
                poll_timeout = _POLL_SECONDS
            message = await self._pubsub.get_message(
                ignore_subscribe_messages=True,
                timeout=poll_timeout,
            )
            if message is not None:
                logger.info("task_signal_received", task_id=str(self._task_id))
                return True


@asynccontextmanager
async def subscribe_task_signal(
    redis_client: Redis,
    task_id: uuid.UUID,
) -> AsyncIterator[TaskSignalSubscription]:
    channel = channel_name(task_id)
    pubsub = redis_client.pubsub()
    await pubsub.subscribe(channel)
    try:
        yield TaskSignalSubscription(pubsub, task_id)
    finally:
        await pubsub.unsubscribe(channel)
        # redis-py: PubSub.aclose без аннотаций типов.
        await pubsub.aclose()  # type: ignore[no-untyped-call]


async def wait_for_task_signal(
    redis_client: Redis,
    task_id: uuid.UUID,
    *,
    timeout: float | None = None,
) -> bool:
    """Блокируется до публикации сигнала на канале задачи.

    Возвращает ``True``, если сигнал получен, ``False`` — если истёк
    ``timeout`` без единого сигнала. ``timeout=None`` ждёт бессрочно.
    """
    async with subscribe_task_signal(redis_client, task_id) as signals:
        return await signals.wait(timeout=timeout)
