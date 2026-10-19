"""Команды управления задачей: пауза, продолжение, остановка (раздел 7.3, 14.2 ТЗ).

API не владеет сессией задачи — ею владеет долгоживущий Celery-таск
(архитектурное решение А плана реализации). Поэтому API лишь записывает
НАМЕРЕНИЕ в Redis и будит воркер сигналом (`services.task_signal`), а
исполняет команду только воркер: между нодами (пауза/остановка) или прямо
во время выполнения (остановка — через `run_stoppable`).

Ключи живут сутки: команда, которую так и не забрал ни один воркер
(задача упала раньше), не должна сработать через неделю при перезапуске —
воркер к тому же очищает команду при захвате задачи.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Coroutine
from enum import StrEnum
from typing import TYPE_CHECKING

from app_logging.config import get_logger
from services.task_signal import publish_task_signal, wait_for_task_signal

if TYPE_CHECKING:
    import uuid
    from collections.abc import Awaitable, Callable

    from redis.asyncio import Redis

logger = get_logger("task_control")

_COMMAND_TTL_SECONDS = 24 * 60 * 60
# Наблюдатель перепроверяет состояние не реже этого интервала, даже если
# сигнал потерялся (опубликован между проверкой и подпиской).
_STOP_POLL_SECONDS = 2.0


class TaskControlCommand(StrEnum):
    PAUSE = "pause"
    RESUME = "resume"
    STOP = "stop"


def _control_key(task_id: uuid.UUID) -> str:
    return f"task:{task_id}:control"


def _manual_stop_key(task_id: uuid.UUID, request_id: uuid.UUID) -> str:
    return f"task:{task_id}:stop:{request_id}"


async def request_task_control(
    redis_client: Redis,
    task_id: uuid.UUID,
    command: TaskControlCommand,
) -> None:
    """Остановка сильнее паузы: уже запрошенный `stop` не перезаписывается
    поздним нажатием «Приостановить»."""
    if command is TaskControlCommand.PAUSE:
        current = await read_task_control(redis_client, task_id)
        if current is TaskControlCommand.STOP:
            logger.info("task_control_pause_ignored_after_stop", task_id=str(task_id))
            return
    await redis_client.set(_control_key(task_id), command.value, ex=_COMMAND_TTL_SECONDS)
    logger.info("task_control_requested", task_id=str(task_id), command=command.value)
    await publish_task_signal(redis_client, task_id)


async def read_task_control(redis_client: Redis, task_id: uuid.UUID) -> TaskControlCommand | None:
    raw = await redis_client.get(_control_key(task_id))
    if raw is None:
        return None
    value = raw.decode() if isinstance(raw, bytes) else str(raw)
    return TaskControlCommand(value)


async def clear_task_control(redis_client: Redis, task_id: uuid.UUID) -> None:
    await redis_client.delete(_control_key(task_id))


# Удаляет ключ, только если в нём всё ещё ожидаемая команда — атомарно,
# чтобы не стереть `stop`, записанный между чтением и удалением.
_CONSUME_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
end
return 0
"""


async def consume_task_control(
    redis_client: Redis,
    task_id: uuid.UUID,
    command: TaskControlCommand,
) -> bool:
    """Забирает команду ``command``; `False` — её уже заменила другая."""
    deleted = await redis_client.eval(
        _CONSUME_SCRIPT,
        1,
        _control_key(task_id),
        command.value,
    )
    return bool(deleted)


async def request_manual_stop(
    redis_client: Redis,
    task_id: uuid.UUID,
    request_id: uuid.UUID,
) -> None:
    """Кнопка ■ для выполняющегося ручного запроса (раздел 7.3)."""
    await redis_client.set(_manual_stop_key(task_id, request_id), "1", ex=_COMMAND_TTL_SECONDS)
    logger.info("manual_stop_requested", task_id=str(task_id), request_id=str(request_id))
    await publish_task_signal(redis_client, task_id)


async def is_manual_stop_requested(
    redis_client: Redis,
    task_id: uuid.UUID,
    request_id: uuid.UUID,
) -> bool:
    return bool(await redis_client.exists(_manual_stop_key(task_id, request_id)))


async def clear_manual_stop(
    redis_client: Redis,
    task_id: uuid.UUID,
    request_id: uuid.UUID,
) -> None:
    await redis_client.delete(_manual_stop_key(task_id, request_id))


async def run_stoppable[T](
    execution: Awaitable[T],
    *,
    redis_client: Redis,
    task_id: uuid.UUID,
    is_stop_requested: Callable[[], Awaitable[bool]],
    on_stop: Callable[[], Awaitable[None]],
) -> T | None:
    """
    Выполняет ``execution``, пока не запрошена остановка.

    ``None`` — выполнение остановлено: корутина отменена, затем вызван
    ``on_stop`` (прерывание хода сессии — после отмены, потому что
    `ClaudeCodeSession` держит мьютекс до конца хода, раздел 6.2).
    Если остановка запрошена ещё до старта, выполнение не начинается вовсе
    и ``on_stop`` не вызывается — прерывать нечего.
    """
    if await is_stop_requested():
        if isinstance(execution, Coroutine):
            execution.close()
        logger.info("execution_skipped_stop_requested", task_id=str(task_id))
        return None
    execution_task = asyncio.ensure_future(execution)

    async def watch() -> None:
        while not await is_stop_requested():
            await wait_for_task_signal(redis_client, task_id, timeout=_STOP_POLL_SECONDS)

    watcher = asyncio.ensure_future(watch())
    try:
        await asyncio.wait({execution_task, watcher}, return_when=asyncio.FIRST_COMPLETED)
    except BaseException:
        execution_task.cancel()
        watcher.cancel()
        raise

    if execution_task.done():
        watcher.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await watcher
        return execution_task.result()

    watcher.result()
    execution_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await execution_task
    logger.info("execution_stopped_by_user", task_id=str(task_id))
    await on_stop()
    return None
