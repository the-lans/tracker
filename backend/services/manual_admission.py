"""
Приём ручных запросов и финализация задачи синхронизируются строкой tasks.
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.enums import ManualRequestStatus
from db.models.prompts import TaskManualRequestQueue
from db.models.tasks import Task
from services.errors import ConflictError, NotFoundError
from services.task_status import SESSION_ACTIVE_STATUSES


async def lock_manual_task(session: AsyncSession, task_id: uuid.UUID) -> Task:
    task = await session.scalar(
        sa.select(Task)
        .where(Task.id == task_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if task is None:
        raise NotFoundError("Задача не найдена")
    return task


def ensure_manual_requests_open(task: Task) -> None:
    if task.status not in SESSION_ACTIVE_STATUSES:
        raise ConflictError("Сессия задачи не активна")
    if task.manual_requests_closed:
        raise ConflictError("Задача завершается: приём новых запросов уже закрыт")


async def close_manual_requests(session: AsyncSession, task_id: uuid.UUID) -> None:
    task = await lock_manual_task(session, task_id)
    task.manual_requests_closed = True
    await session.commit()


async def ensure_manual_requests_drained(session: AsyncSession, task_id: uuid.UUID) -> None:
    unfinished = await session.scalar(
        sa.select(TaskManualRequestQueue.id)
        .where(
            TaskManualRequestQueue.task_id == task_id,
            TaskManualRequestQueue.status.in_(
                (ManualRequestStatus.QUEUED, ManualRequestStatus.PROCESSING)
            ),
        )
        .limit(1)
    )
    if unfinished is not None:
        raise ConflictError("Нельзя завершить задачу: остались необработанные ручные запросы")
