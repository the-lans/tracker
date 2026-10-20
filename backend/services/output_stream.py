"""
Потоковый вывод ответа LLM в ленту задачи (раздел 15.2 ТЗ).

Воркер публикует фрагменты ответа в канал Redis ``task:{task_id}:output``,
WebSocket задачи (`ws/tasks.py`) пересылает их браузеру. Итоговый текст
по-прежнему пишется в `node_logs` в конце хода: поток — только отображение,
потерянный фрагмент ничего не ломает.
"""

from __future__ import annotations

import json
import uuid
from typing import TYPE_CHECKING

from redis.exceptions import RedisError

from app_logging.config import get_logger

if TYPE_CHECKING:
    from redis.asyncio import Redis

    from clients.claude_agent import TextDeltaHandler
    from services.plan_mode import ActiveNodeContext

logger = get_logger("output_stream")


def output_channel_name(task_id: uuid.UUID) -> str:
    return f"task:{task_id}:output"


async def publish_output_delta(
    redis_client: Redis,
    *,
    task_id: uuid.UUID,
    node_log_id: uuid.UUID,
    text: str,
) -> None:
    payload = json.dumps({"node_log_id": str(node_log_id), "text": text}, ensure_ascii=False)
    await redis_client.publish(output_channel_name(task_id), payload)


def build_output_publisher(redis_client: Redis, context: ActiveNodeContext) -> TextDeltaHandler:
    """Фрагмент адресуется записи `node_logs`, чей ход сейчас идёт (`ActiveNodeContext`)."""

    async def publish(text: str) -> None:
        if context.task_id is None or context.node_log_id is None:
            return
        try:
            await publish_output_delta(
                redis_client,
                task_id=context.task_id,
                node_log_id=context.node_log_id,
                text=text,
            )
        except RedisError:
            # Поток — лишь отображение: ход продолжается, текст сохранится в БД.
            logger.warning("output_delta_publish_failed", task_id=str(context.task_id))

    return publish
