"""
События дня «Дейли» (раздел 15.8 ТЗ). Ручное событие пользователь создаёт,
правит и удаляет; событие из Google Calendar (раздел 19.8) приходит
синхронизацией и в трекере только скрывается или показывается снова.

День события — день трекера: время раньше начала дня относится к ночи после
выбранного дня. Добавлять события можно на дни окна «Истории».
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import TYPE_CHECKING

from app_logging.config import get_logger
from db.models.daily import DailyEvent
from db.models.enums import DailyEventSource
from services.access import get_personal_or_404
from services.errors import ConflictError, ValidationError
from services.tracker_day import ensure_in_history, moment_in_day

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from db.models.users import User
    from services.daily_clock import DailyClock

logger = get_logger("daily_events")

MAX_EVENT_TITLE_LENGTH = 200
MAX_EVENT_NOTES_LENGTH = 2000

_NOT_FOUND = "Событие не найдено"
_EMPTY_TITLE = "Название события не может быть пустым"
_TITLE_TOO_LONG = f"Название события — не длиннее {MAX_EVENT_TITLE_LENGTH} символов"
_NOTES_TOO_LONG = f"Заметка к событию — не длиннее {MAX_EVENT_NOTES_LENGTH} символов"
_END_WITHOUT_START = "Конец события задаётся только вместе с началом"
_END_BEFORE_START = "Событие должно заканчиваться позже, чем начинается"
_CALENDAR_READ_ONLY = "Событие из Google Calendar меняется в календаре; в трекере его можно скрыть"


@dataclass(frozen=True, slots=True)
class ManualEventValues:
    day: date
    title: str
    notes: str | None = None
    start_time: time | None = None
    end_time: time | None = None


@dataclass(frozen=True, slots=True)
class _EventMoments:
    starts_at: datetime | None
    ends_at: datetime | None


def _clean_text(values: ManualEventValues) -> tuple[str, str | None]:
    title = values.title.strip()
    if not title:
        raise ValidationError(_EMPTY_TITLE)
    if len(title) > MAX_EVENT_TITLE_LENGTH:
        raise ValidationError(_TITLE_TOO_LONG)
    notes = (values.notes or "").strip() or None
    if notes is not None and len(notes) > MAX_EVENT_NOTES_LENGTH:
        raise ValidationError(_NOTES_TOO_LONG)
    return title, notes


def _moments(values: ManualEventValues, clock: DailyClock) -> _EventMoments:
    ensure_in_history(clock.window, values.day)
    if values.start_time is None:
        if values.end_time is not None:
            raise ValidationError(_END_WITHOUT_START)
        return _EventMoments(starts_at=None, ends_at=None)
    starts_at = moment_in_day(values.day, values.start_time, clock.day_start)
    if values.end_time is None:
        return _EventMoments(starts_at=starts_at, ends_at=None)
    ends_at = moment_in_day(values.day, values.end_time, clock.day_start)
    if ends_at <= starts_at:
        raise ValidationError(_END_BEFORE_START)
    return _EventMoments(starts_at=starts_at, ends_at=ends_at)


def _apply(event: DailyEvent, values: ManualEventValues, clock: DailyClock) -> None:
    title, notes = _clean_text(values)
    moments = _moments(values, clock)
    event.day = values.day
    event.end_day = values.day
    event.title = title
    event.notes = notes
    event.starts_at = moments.starts_at
    event.ends_at = moments.ends_at


async def get_event_for_user(
    db_session: AsyncSession,
    event_id: uuid.UUID,
    *,
    user: User,
) -> DailyEvent:
    return await get_personal_or_404(
        db_session,
        DailyEvent,
        event_id,
        user=user,
        not_found=_NOT_FOUND,
    )


async def create_manual_event(
    db_session: AsyncSession,
    *,
    user: User,
    values: ManualEventValues,
    clock: DailyClock,
) -> DailyEvent:
    event = DailyEvent(user_id=user.id, source=DailyEventSource.MANUAL, hidden=False)
    _apply(event, values, clock)
    db_session.add(event)
    await db_session.commit()
    logger.info("daily_event_created", event_id=str(event.id), day=values.day.isoformat())
    return event


async def update_manual_event(
    db_session: AsyncSession,
    *,
    user: User,
    event_id: uuid.UUID,
    values: ManualEventValues,
    clock: DailyClock,
) -> DailyEvent:
    event = await get_event_for_user(db_session, event_id, user=user)
    if event.source is not DailyEventSource.MANUAL:
        raise ConflictError(_CALENDAR_READ_ONLY)
    _apply(event, values, clock)
    await db_session.commit()
    logger.info("daily_event_updated", event_id=str(event.id))
    return event


async def set_event_hidden(
    db_session: AsyncSession,
    *,
    user: User,
    event_id: uuid.UUID,
    hidden: bool,
) -> DailyEvent:
    event = await get_event_for_user(db_session, event_id, user=user)
    event.hidden = hidden
    await db_session.commit()
    logger.info("daily_event_visibility_changed", event_id=str(event.id), hidden=hidden)
    return event


async def delete_manual_event(
    db_session: AsyncSession,
    *,
    user: User,
    event_id: uuid.UUID,
) -> None:
    event = await get_event_for_user(db_session, event_id, user=user)
    if event.source is not DailyEventSource.MANUAL:
        raise ConflictError(_CALENDAR_READ_ONLY)
    await db_session.delete(event)
    await db_session.commit()
    logger.info("daily_event_deleted", event_id=str(event_id))
