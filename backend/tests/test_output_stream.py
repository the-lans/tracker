"""Тесты `services/output_stream.py` (раздел 15.2 ТЗ)."""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import TYPE_CHECKING, Any

from redis.exceptions import ConnectionError as RedisConnectionError

from services.output_stream import build_output_publisher, output_channel_name
from services.plan_mode import ActiveNodeContext

if TYPE_CHECKING:
    from redis.asyncio import Redis


class TestOutputPublisher:
    async def test_addresses_active_node_log(self, redis_client: Redis) -> None:
        context = ActiveNodeContext()
        task_id = uuid.uuid4()
        node_log_id = uuid.uuid4()
        pubsub = redis_client.pubsub()
        await pubsub.subscribe(output_channel_name(task_id))
        publish = build_output_publisher(redis_client, context)

        await publish("до начала хода")
        context.activate(node_log_id=node_log_id, task_id=task_id)
        await publish("фрагмент")

        messages: list[dict[str, Any]] = []
        for _ in range(20):
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.2)
            if message is not None:
                messages.append(json.loads(message["data"]))
                break
            await asyncio.sleep(0)
        await pubsub.aclose()  # type: ignore[no-untyped-call]

        assert messages == [{"node_log_id": str(node_log_id), "text": "фрагмент"}]

    async def test_redis_failure_does_not_break_turn(self) -> None:
        class BrokenRedis:
            async def publish(self, _channel: str, _payload: str) -> int:
                raise RedisConnectionError("Redis недоступен")

        context = ActiveNodeContext()
        context.activate(node_log_id=uuid.uuid4(), task_id=uuid.uuid4())
        publish = build_output_publisher(BrokenRedis(), context)  # type: ignore[arg-type]

        await publish("фрагмент")
