"""Тесты `services/task_control.py` — команды управления задачей (раздел 7.3, 14.2)."""

from __future__ import annotations

import asyncio
import uuid
from typing import TYPE_CHECKING

import pytest

from services.task_control import (
    TaskControlCommand,
    clear_manual_stop,
    clear_task_control,
    consume_bridge_reconnect,
    consume_task_control,
    is_manual_stop_requested,
    read_task_control,
    request_bridge_reconnect,
    request_manual_stop,
    request_task_control,
    run_stoppable,
)
from services.task_signal import wait_for_task_signal

if TYPE_CHECKING:
    from redis.asyncio import Redis


async def test_request_task_control_stores_command(redis_client: Redis) -> None:
    task_id = uuid.uuid4()

    await request_task_control(redis_client, task_id, TaskControlCommand.PAUSE)

    assert await read_task_control(redis_client, task_id) is TaskControlCommand.PAUSE
    await clear_task_control(redis_client, task_id)
    assert await read_task_control(redis_client, task_id) is None


async def test_pause_does_not_override_requested_stop(redis_client: Redis) -> None:
    task_id = uuid.uuid4()

    await request_task_control(redis_client, task_id, TaskControlCommand.STOP)
    await request_task_control(redis_client, task_id, TaskControlCommand.PAUSE)

    assert await read_task_control(redis_client, task_id) is TaskControlCommand.STOP


async def test_consume_takes_only_the_expected_command(redis_client: Redis) -> None:
    task_id = uuid.uuid4()
    await request_task_control(redis_client, task_id, TaskControlCommand.PAUSE)
    await request_task_control(redis_client, task_id, TaskControlCommand.STOP)

    assert await consume_task_control(redis_client, task_id, TaskControlCommand.PAUSE) is False
    assert await read_task_control(redis_client, task_id) is TaskControlCommand.STOP
    assert await consume_task_control(redis_client, task_id, TaskControlCommand.STOP) is True
    assert await read_task_control(redis_client, task_id) is None


async def test_manual_stop_flag_is_per_request(redis_client: Redis) -> None:
    task_id, request_id = uuid.uuid4(), uuid.uuid4()

    await request_manual_stop(redis_client, task_id, request_id)

    assert await is_manual_stop_requested(redis_client, task_id, request_id)
    assert not await is_manual_stop_requested(redis_client, task_id, uuid.uuid4())
    await clear_manual_stop(redis_client, task_id, request_id)
    assert not await is_manual_stop_requested(redis_client, task_id, request_id)


async def test_run_stoppable_returns_result_when_not_stopped(redis_client: Redis) -> None:
    stops: list[str] = []

    async def finish() -> str:
        await asyncio.sleep(0.01)
        return "готово"

    async def never() -> bool:
        return False

    async def on_stop() -> None:
        stops.append("stop")

    result = await run_stoppable(
        finish(),
        redis_client=redis_client,
        task_id=uuid.uuid4(),
        is_stop_requested=never,
        on_stop=on_stop,
    )

    assert result == "готово"
    assert stops == []


async def test_run_stoppable_cancels_execution_on_stop_signal(redis_client: Redis) -> None:
    task_id = uuid.uuid4()
    cancelled = asyncio.Event()
    stops: list[str] = []

    async def hang_forever() -> str:
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            cancelled.set()
            raise
        return "не дойдёт"

    async def stop_requested() -> bool:
        return await read_task_control(redis_client, task_id) is TaskControlCommand.STOP

    async def on_stop() -> None:
        assert cancelled.is_set(), "сессию прерывают только после отмены хода"
        stops.append("stop")

    async def press_stop() -> None:
        await asyncio.sleep(0.2)
        await request_task_control(redis_client, task_id, TaskControlCommand.STOP)

    presser = asyncio.ensure_future(press_stop())
    result = await asyncio.wait_for(
        run_stoppable(
            hang_forever(),
            redis_client=redis_client,
            task_id=task_id,
            is_stop_requested=stop_requested,
            on_stop=on_stop,
        ),
        timeout=5,
    )
    await presser

    assert result is None
    assert stops == ["stop"]


async def test_run_stoppable_propagates_execution_error(redis_client: Redis) -> None:
    async def explode() -> str:
        raise RuntimeError("сбой ноды")

    async def never() -> bool:
        return False

    async def on_stop() -> None:
        return None

    with pytest.raises(RuntimeError, match="сбой ноды"):
        await run_stoppable(
            explode(),
            redis_client=redis_client,
            task_id=uuid.uuid4(),
            is_stop_requested=never,
            on_stop=on_stop,
        )


class TestRunStoppableBeforeStart:
    async def test_skips_execution_and_on_stop(
        self,
        redis_client: Redis,
    ) -> None:
        started: list[str] = []
        stops: list[str] = []

        async def execution() -> str:
            started.append("start")
            return "не должно выполниться"

        async def always() -> bool:
            return True

        async def on_stop() -> None:
            stops.append("stop")

        result = await run_stoppable(
            execution(),
            redis_client=redis_client,
            task_id=uuid.uuid4(),
            is_stop_requested=always,
            on_stop=on_stop,
        )

        assert result is None
        assert started == []
        assert stops == [], "прерывать нечего — ход не начинался"


class TestBridgeReconnect:
    async def test_consumed_once(self, redis_client: Redis) -> None:
        task_id = uuid.uuid4()
        waiter = asyncio.ensure_future(wait_for_task_signal(redis_client, task_id, timeout=5))
        await asyncio.sleep(0.1)

        await request_bridge_reconnect(redis_client, task_id)

        assert await waiter is True
        assert await consume_bridge_reconnect(redis_client, task_id) is True
        assert await consume_bridge_reconnect(redis_client, task_id) is False

    async def test_independent_of_control_command(self, redis_client: Redis) -> None:
        task_id = uuid.uuid4()
        await request_task_control(redis_client, task_id, TaskControlCommand.STOP)

        await request_bridge_reconnect(redis_client, task_id)

        assert await read_task_control(redis_client, task_id) is TaskControlCommand.STOP
