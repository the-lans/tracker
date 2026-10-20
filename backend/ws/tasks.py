"""
WebSocket-канал задачи (раздел 15.2, 18.1 ТЗ): `/ws/tasks/{task_id}/status`.

Два вида событий в одном соединении:

- ``{"type": "status", ...}`` — смена `tasks.status`. Реализовано короткими
  опросами БД (~1 раз в секунду), а не отдельным Redis-каналом: статус
  меняется из МНОГИХ мест (`services/task_status.py`, `services/plan_mode.py`,
  `services/autostart.py`, `services/gitlab_sync.py`), и протаскивать
  publish через все них означало бы рисковать разойтись местами.
  Полноценный push (раздел 18, Web Push) на закрытую вкладку — отдельный
  механизм (`services/notifications.py`, `services/push_notifications.py`).
- ``{"type": "output_delta", "node_log_id", "text"}`` — фрагменты ответа
  LLM по мере генерации (раздел 15.2). Их публикует воркер в Redis
  (`services/output_stream.py`), опросом БД их не получить.
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from redis.asyncio import Redis

from app_logging.config import get_logger
from db.models.enums import TaskStatus
from db.models.tasks import Task
from db.session import async_session_factory
from services.auth_tokens import InvalidSessionTokenError, verify_session_token
from services.output_stream import output_channel_name

router = APIRouter()

logger = get_logger("ws.tasks")

_POLL_INTERVAL_SECONDS = 1.0
_TASK_NOT_FOUND_CLOSE_CODE = 4404
_UNAUTHORIZED_CLOSE_CODE = 4401

SendJson = Callable[[dict[str, Any]], Awaitable[None]]


async def _fetch_status(task_id: uuid.UUID) -> TaskStatus | None:
    async with async_session_factory() as db_session:
        task = await db_session.get(Task, task_id)
        return task.status if task is not None else None


async def stream_task_events(
    send: SendJson,
    *,
    task_id: uuid.UUID,
    redis_client: Redis,
    fetch_status: Callable[[uuid.UUID], Awaitable[TaskStatus | None]] = _fetch_status,
) -> None:
    """Пересылает события задачи, пока она существует; возврат — задача удалена."""
    pubsub = redis_client.pubsub()
    await pubsub.subscribe(output_channel_name(task_id))
    loop = asyncio.get_running_loop()
    last_status: TaskStatus | None = None
    next_status_check = loop.time()
    try:
        while True:
            if loop.time() >= next_status_check:
                status = await fetch_status(task_id)
                if status is None:
                    return
                if status != last_status:
                    await send({"type": "status", "task_id": str(task_id), "status": status.value})
                    last_status = status
                next_status_check = loop.time() + _POLL_INTERVAL_SECONDS
            message = await pubsub.get_message(
                ignore_subscribe_messages=True,
                timeout=max(0.0, next_status_check - loop.time()),
            )
            if message is not None:
                delta = json.loads(message["data"])
                await send({"type": "output_delta", **delta})
    finally:
        await pubsub.unsubscribe()
        # redis-py: PubSub.aclose без аннотаций типов.
        await pubsub.aclose()  # type: ignore[no-untyped-call]


async def _wait_for_disconnect(websocket: WebSocket) -> None:
    """
    Клиент ничего не присылает — читать нужно только ради сообщения о
    закрытии: без него поток событий не узнал бы, что вкладку закрыли.
    """
    while True:
        message = await websocket.receive()
        if message["type"] == "websocket.disconnect":
            return


async def serve_task_events(
    websocket: WebSocket,
    *,
    task_id: uuid.UUID,
    redis_client: Redis,
    fetch_status: Callable[[uuid.UUID], Awaitable[TaskStatus | None]] = _fetch_status,
) -> None:
    """
    Поток событий до удаления задачи или до закрытия сокета клиентом —
    смотря что раньше; оставшаяся сторона отменяется, подписка Redis
    закрывается в `stream_task_events`.
    """
    streaming = asyncio.create_task(
        stream_task_events(
            websocket.send_json,
            task_id=task_id,
            redis_client=redis_client,
            fetch_status=fetch_status,
        ),
    )
    disconnected = asyncio.create_task(_wait_for_disconnect(websocket))
    done, pending = await asyncio.wait(
        {streaming, disconnected},
        return_when=asyncio.FIRST_COMPLETED,
    )
    for remaining in pending:
        remaining.cancel()
    await asyncio.gather(*pending, return_exceptions=True)
    if streaming in done:
        streaming.result()
        await websocket.close(code=_TASK_NOT_FOUND_CLOSE_CODE)
        return
    logger.info("ws_task_status_disconnected", task_id=str(task_id))


@router.websocket("/ws/tasks/{task_id}/status")
async def task_status_stream(websocket: WebSocket, task_id: uuid.UUID) -> None:
    token = websocket.query_params.get("token")
    if token is None:
        await websocket.close(code=_UNAUTHORIZED_CLOSE_CODE)
        return
    try:
        verify_session_token(token)
    except InvalidSessionTokenError:
        await websocket.close(code=_UNAUTHORIZED_CLOSE_CODE)
        return

    await websocket.accept()
    redis_client = Redis.from_url(os.environ["REDIS_URL"])
    try:
        await serve_task_events(websocket, task_id=task_id, redis_client=redis_client)
    except WebSocketDisconnect:
        logger.info("ws_task_status_disconnected", task_id=str(task_id))
    finally:
        await redis_client.aclose()
