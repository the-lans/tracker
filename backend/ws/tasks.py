"""WebSocket-канал статуса задачи (раздел 18.1 ТЗ): `/ws/tasks/{task_id}/status`.

Реализовано короткими опросами БД (~1 раз в секунду), а не через
дополнительный Redis pub/sub-канал специально под broadcast: изменения
`tasks.status` происходят из МНОГИХ разных мест (`services/task_status.py`,
`services/plan_mode.py`, `services/autostart.py`, `services/gitlab_sync.py`)
— заводить отдельный канал оповещения означало бы протащить publish-вызов
через все них, рискуя разойтись местами. Опрос с интервалом в секунду даёт
ту же ощутимую "мгновенность" для открытой вкладки браузера при заметно
меньшей связности кода; полноценный push (раздел 18, Web Push) на закрытую
вкладку — отдельный, не заменяемый этим механизм (`services/notifications.py`,
`services/push_notifications.py`, этап 14 плана реализации).
"""

from __future__ import annotations

import asyncio
import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app_logging.config import get_logger
from db.models.enums import TaskStatus
from db.models.tasks import Task
from db.session import async_session_factory
from services.auth_tokens import InvalidSessionTokenError, verify_session_token

router = APIRouter()

logger = get_logger("ws.tasks")

_POLL_INTERVAL_SECONDS = 1.0


async def _fetch_status(task_id: uuid.UUID) -> TaskStatus | None:
    async with async_session_factory() as db_session:
        task = await db_session.get(Task, task_id)
        return task.status if task is not None else None


@router.websocket("/ws/tasks/{task_id}/status")
async def task_status_stream(websocket: WebSocket, task_id: uuid.UUID) -> None:
    token = websocket.query_params.get("token")
    if token is None:
        await websocket.close(code=4401)
        return
    try:
        verify_session_token(token)
    except InvalidSessionTokenError:
        await websocket.close(code=4401)
        return

    await websocket.accept()
    last_status: TaskStatus | None = None
    try:
        while True:
            status = await _fetch_status(task_id)
            if status is None:
                await websocket.close(code=4404)
                return
            if status != last_status:
                await websocket.send_json({"task_id": str(task_id), "status": status.value})
                last_status = status
            await asyncio.sleep(_POLL_INTERVAL_SECONDS)
    except WebSocketDisconnect:
        logger.info("ws_task_status_disconnected", task_id=str(task_id))
