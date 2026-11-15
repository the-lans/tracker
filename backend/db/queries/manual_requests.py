"""Запросы для ручных запусков промтов задачи."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import sqlalchemy as sa

from db.models.enums import LibraryPromptRunStatus, ManualRequestStatus
from db.models.prompts import TaskLibraryPrompt, TaskManualRequestQueue

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy.ext.asyncio import AsyncSession


async def active_prompt_request(
    db_session: AsyncSession,
    *,
    task_id: uuid.UUID,
    node_id: uuid.UUID,
) -> uuid.UUID | None:
    """Вернуть активный ручной запуск библиотечного промта."""
    return await db_session.scalar(
        sa.select(TaskManualRequestQueue.id)
        .where(
            TaskManualRequestQueue.task_id == task_id,
            TaskManualRequestQueue.node_id == node_id,
            TaskManualRequestQueue.command_name.is_(None),
            TaskManualRequestQueue.status.in_(
                (ManualRequestStatus.QUEUED, ManualRequestStatus.PROCESSING),
            ),
        )
        .limit(1),
    )


async def cancel_queued_requests(
    db_session: AsyncSession,
    *,
    task_id: uuid.UUID,
    now: datetime,
) -> list[tuple[uuid.UUID | None, str | None]]:
    """Отменить ожидающие запросы и вернуть связанные ноды и команды."""
    rows = await db_session.execute(
        sa.update(TaskManualRequestQueue)
        .where(
            TaskManualRequestQueue.task_id == task_id,
            TaskManualRequestQueue.status == ManualRequestStatus.QUEUED,
        )
        .values(status=ManualRequestStatus.CANCELLED, processed_at=now)
        .returning(TaskManualRequestQueue.node_id, TaskManualRequestQueue.command_name),
    )
    return [(row.node_id, row.command_name) for row in rows]


async def mark_queued_prompt_stopped(
    db_session: AsyncSession,
    *,
    task_id: uuid.UUID,
    node_id: uuid.UUID,
) -> None:
    """Пометить ожидающий промт остановленным."""
    await db_session.execute(
        sa.update(TaskLibraryPrompt)
        .where(
            TaskLibraryPrompt.task_id == task_id,
            TaskLibraryPrompt.node_id == node_id,
            TaskLibraryPrompt.last_run_status == LibraryPromptRunStatus.QUEUED,
        )
        .values(last_run_status=LibraryPromptRunStatus.STOPPED),
    )
