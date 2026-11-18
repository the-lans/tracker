"""Запросы к `task_session_events` — события сессии для ленты чата (раздел 15.2)."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import sqlalchemy as sa

from db.models.session_events import TaskSessionEvent

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def list_session_events(
    db_session: AsyncSession,
    task_id: uuid.UUID,
) -> list[TaskSessionEvent]:
    stmt = (
        sa.select(TaskSessionEvent)
        .where(TaskSessionEvent.task_id == task_id)
        .order_by(TaskSessionEvent.created_at, TaskSessionEvent.id)
    )
    return list((await db_session.execute(stmt)).scalars().all())
