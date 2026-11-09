"""
Общее для эндпоинтов задачи: доступ, проверка статуса, сигнал воркеру.
"""

from __future__ import annotations

import uuid
from enum import Enum

from sqlalchemy.ext.asyncio import AsyncSession

from db.models.enums import ManualRequestStatus, TaskStatus
from db.models.tasks import Task
from db.models.users import User
from services.access import get_task_for_user
from services.errors import ConflictError
from services.redis_connection import redis_connection
from services.task_signal import publish_task_signal
from tasks.session_worker import run_task_session

TASKS_PREFIX = "/tasks"
TASKS_TAGS: list[str | Enum] = ["tasks"]

ACTIVE_REQUEST_STATUSES = (ManualRequestStatus.QUEUED, ManualRequestStatus.PROCESSING)


async def get_task_or_404(db_session: AsyncSession, task_id: uuid.UUID, user: User) -> Task:
    """Раздел 19.2: чужая задача для `user` неотличима от несуществующей."""
    return await get_task_for_user(db_session, task_id, user=user)


def require_status(task: Task, allowed: frozenset[TaskStatus], message: str) -> None:
    if task.status not in allowed:
        raise ConflictError(message)


async def publish_signal(task_id: uuid.UUID) -> None:
    """Будит воркер сессии задачи (правило 16): ручной запрос в очереди."""
    async with redis_connection() as redis_client:
        await publish_task_signal(redis_client, task_id)


async def wake_session_for_request(task: Task) -> None:
    """
    Ручной запрос в очереди: воркер, владеющий сессией, будится сигналом. В
    «Уточняется» без идущего чата сессией никто не владеет — запускается
    воркер в режиме чата (раздел 14.4).
    """
    if task.status is TaskStatus.REFINING and not task.chat_active:
        run_task_session.delay(str(task.id), chat_only=True)
        return
    await publish_signal(task.id)
