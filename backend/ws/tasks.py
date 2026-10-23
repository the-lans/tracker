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

Авторизация (раздел 18.1, 19.2): токен сессии приходит первым сообщением
``{"type": "auth", "token": ...}``, а не в адресе — адрес попадает в журналы
запросов. Доступ к каналу перепроверяется во время потока: заблокированный
пользователь или потерявший доступ к задаче отключается.
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
from services.access import authorize_task_stream
from services.auth_tokens import InvalidSessionTokenError, verify_session_token
from services.errors import NotFoundError, UnauthorizedError
from services.output_stream import output_channel_name

router = APIRouter()

logger = get_logger("ws.tasks")

_POLL_INTERVAL_SECONDS = 1.0
_TASK_NOT_FOUND_CLOSE_CODE = 4404
_UNAUTHORIZED_CLOSE_CODE = 4401
# Сколько ждать сообщения с токеном после подключения.
AUTH_TIMEOUT_SECONDS = 5.0
# Доступ перепроверяется каждые N опросов статуса (~N секунд).
ACCESS_RECHECK_POLLS = 10
_AUTH_MESSAGE_TYPE = "auth"

SendJson = Callable[[dict[str, Any]], Awaitable[None]]
# Код закрытия, если доступ к каналу потерян; `None` — доступ есть.
AccessCheck = Callable[[], Awaitable[int | None]]


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
    check_access: AccessCheck | None = None,
) -> int:
    """Пересылает события задачи; возвращает код закрытия: задача удалена или доступ потерян."""
    pubsub = redis_client.pubsub()
    await pubsub.subscribe(output_channel_name(task_id))
    loop = asyncio.get_running_loop()
    last_status: TaskStatus | None = None
    next_status_check = loop.time()
    polls = 0
    try:
        while True:
            if loop.time() >= next_status_check:
                status = await fetch_status(task_id)
                if status is None:
                    return _TASK_NOT_FOUND_CLOSE_CODE
                if status != last_status:
                    await send({"type": "status", "task_id": str(task_id), "status": status.value})
                    last_status = status
                polls += 1
                if check_access is not None and polls % ACCESS_RECHECK_POLLS == 0:
                    close_code = await check_access()
                    if close_code is not None:
                        return close_code
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
    check_access: AccessCheck | None = None,
) -> None:
    """
    Поток событий до удаления задачи, потери доступа или закрытия сокета
    клиентом — смотря что раньше; оставшаяся сторона отменяется, подписка
    Redis закрывается в `stream_task_events`.
    """
    streaming = asyncio.create_task(
        stream_task_events(
            websocket.send_json,
            task_id=task_id,
            redis_client=redis_client,
            fetch_status=fetch_status,
            check_access=check_access,
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
        await websocket.close(code=streaming.result())
        return
    logger.info("ws_task_status_disconnected", task_id=str(task_id))


async def _access_denied_close_code(*, user_id: uuid.UUID, task_id: uuid.UUID) -> int | None:
    """Раздел 19.2: канал задачи — только для активного автора задачи или `admin`."""
    async with async_session_factory() as db_session:
        try:
            await authorize_task_stream(db_session, user_id=user_id, task_id=task_id)
        except UnauthorizedError:
            return _UNAUTHORIZED_CLOSE_CODE
        except NotFoundError:
            return _TASK_NOT_FOUND_CLOSE_CODE
    return None


async def receive_auth_token(websocket: WebSocket) -> str | None:
    """Токен из первого сообщения ``{"type": "auth", "token": ...}``; `None` — его нет."""
    try:
        message = await asyncio.wait_for(websocket.receive_json(), timeout=AUTH_TIMEOUT_SECONDS)
    except (TimeoutError, WebSocketDisconnect, ValueError):
        return None
    if not isinstance(message, dict) or message.get("type") != _AUTH_MESSAGE_TYPE:
        return None
    token = message.get("token")
    return token if isinstance(token, str) else None


@router.websocket("/ws/tasks/{task_id}/status")
async def task_status_stream(websocket: WebSocket, task_id: uuid.UUID) -> None:
    await websocket.accept()
    token = await receive_auth_token(websocket)
    if token is None:
        await websocket.close(code=_UNAUTHORIZED_CLOSE_CODE)
        return
    try:
        user_id = verify_session_token(token)
    except InvalidSessionTokenError:
        await websocket.close(code=_UNAUTHORIZED_CLOSE_CODE)
        return

    close_code = await _access_denied_close_code(user_id=user_id, task_id=task_id)
    if close_code is not None:
        await websocket.close(code=close_code)
        return

    async def check_access() -> int | None:
        return await _access_denied_close_code(user_id=user_id, task_id=task_id)

    redis_client = Redis.from_url(os.environ["REDIS_URL"])
    try:
        await serve_task_events(
            websocket,
            task_id=task_id,
            redis_client=redis_client,
            check_access=check_access,
        )
    except WebSocketDisconnect:
        logger.info("ws_task_status_disconnected", task_id=str(task_id))
    finally:
        await redis_client.aclose()
