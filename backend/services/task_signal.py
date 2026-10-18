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

from redis.asyncio import Redis

from app_logging.config import get_logger

logger = get_logger("task_signal")


def channel_name(task_id: uuid.UUID) -> str:
    return f"task:{task_id}:signal"


async def publish_task_signal(redis_client: Redis, task_id: uuid.UUID) -> None:
    channel = channel_name(task_id)
    await redis_client.publish(channel, "1")
    logger.info("task_signal_published", task_id=str(task_id), channel=channel)


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
    channel = channel_name(task_id)
    pubsub = redis_client.pubsub()
    await pubsub.subscribe(channel)
    loop = asyncio.get_event_loop()
    deadline = None if timeout is None else loop.time() + timeout
    try:
        while True:
            if deadline is not None:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    logger.info("task_signal_wait_timed_out", task_id=str(task_id))
                    return False
                poll_timeout = min(remaining, 1.0)
            else:
                poll_timeout = 1.0
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=poll_timeout)
            if message is not None:
                logger.info("task_signal_received", task_id=str(task_id))
                return True
    finally:
        await pubsub.unsubscribe(channel)
        # redis-py: PubSub.aclose без аннотаций типов.
        await pubsub.aclose()  # type: ignore[no-untyped-call]
