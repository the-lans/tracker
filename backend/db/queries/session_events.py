"""
Запросы к `task_session_events` — события сессии для ленты чата (раздел 15.2).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

import sqlalchemy as sa

from db.models.logs import NodeLog
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


async def get_last_session_event(
    db_session: AsyncSession,
    task_id: uuid.UUID,
) -> TaskSessionEvent | None:
    stmt = (
        sa.select(TaskSessionEvent)
        .where(TaskSessionEvent.task_id == task_id)
        .order_by(TaskSessionEvent.created_at.desc(), TaskSessionEvent.id.desc())
        .limit(1)
    )
    return (await db_session.execute(stmt)).scalar_one_or_none()


async def has_node_log_since(
    db_session: AsyncSession,
    task_id: uuid.UUID,
    since: datetime,
) -> bool:
    stmt = (
        sa.select(NodeLog.id)
        .where(NodeLog.task_id == task_id, NodeLog.started_at >= since)
        .limit(1)
    )
    return (await db_session.execute(stmt)).first() is not None
