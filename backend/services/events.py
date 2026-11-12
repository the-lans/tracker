"""
Лента событий (раздел 18.4 ТЗ): всё, о чём трекер уведомляет, плюс итоги
бэкапов и смена итога периодических задач. Запись делает только
`services/notifications.py` — в тех же местах, что и push, поэтому событие
появляется один раз на однократное изменение состояния (правило 12).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.exc import SQLAlchemyError

from app_logging.config import get_logger
from db.models.enums import EventAudience, EventCategory
from db.models.events import Event

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger("events")

MAX_EVENTS_PAGE = 100


@dataclass(frozen=True, slots=True)
class EventDraft:
    category: EventCategory
    event_type: str
    title: str
    body: str
    task_id: uuid.UUID | None = None


async def record_event(
    db_session: AsyncSession,
    draft: EventDraft,
    *,
    user_id: uuid.UUID | None,
) -> None:
    """
    `user_id` — адресат события; `None` — событие всех администраторов.
    Сбой записи не мешает push-уведомлению: событие только логируется.
    """
    db_session.add(
        Event(
            audience=EventAudience.ADMINS if user_id is None else EventAudience.USER,
            user_id=user_id,
            category=draft.category,
            event_type=draft.event_type,
            title=draft.title,
            body=draft.body,
            task_id=draft.task_id,
        ),
    )
    try:
        await db_session.commit()
    except SQLAlchemyError:
        await db_session.rollback()
        logger.exception("event_record_failed", event_type=draft.event_type)


@dataclass(frozen=True, slots=True)
class EventFilters:
    audience: EventAudience
    user_id: uuid.UUID
    category: EventCategory | None = None
    before: datetime | None = None


async def list_events(
    db_session: AsyncSession,
    filters: EventFilters,
    *,
    limit: int,
) -> Sequence[Event]:
    """Новые сверху; следующая страница — `before` = время последнего события."""
    stmt = sa.select(Event).where(Event.audience == filters.audience)
    if filters.audience is EventAudience.USER:
        stmt = stmt.where(Event.user_id == filters.user_id)
    if filters.category is not None:
        stmt = stmt.where(Event.category == filters.category)
    if filters.before is not None:
        stmt = stmt.where(Event.created_at < filters.before)
    stmt = stmt.order_by(Event.created_at.desc(), Event.id.desc()).limit(
        min(limit, MAX_EVENTS_PAGE),
    )
    return (await db_session.scalars(stmt)).all()


async def purge_old_events(
    db_session: AsyncSession,
    *,
    now: datetime,
    threshold_days: int,
) -> int:
    """Раздел 16.2: события старше порога удаляются вместе с ротацией логов."""
    result = await db_session.execute(
        sa.delete(Event).where(Event.created_at < now - timedelta(days=threshold_days)),
    )
    await db_session.commit()
    return int(result.rowcount)  # type: ignore[attr-defined]
