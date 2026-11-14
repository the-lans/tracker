"""
Синхронизация Google Calendar с «Дейли» (разделы 15.8, 19.8 ТЗ): события
выбранных календарей за окно «Истории» — 7 прошлых дней, сегодня и завтра —
переносятся в `daily_events`. Синхронизация только читает календарь.

Событие обновляется по `(calendar_id, external_id)`, а отметка «скрыто»
пользователя при этом сохраняется. Событие окна, которого в календаре больше
нет (удалено, отменено, календарь снят с синхронизации), удаляется. День
события со временем — день трекера его начала; событие на весь день берёт
даты календаря как есть (конец у Google исключающий).

Синхронизация пользователя идёт под распределённой блокировкой: периодическая
задача и кнопка «Обновить» не пишут события одновременно (правило 12).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING

from app_logging.config import get_logger
from clients.google_calendar import CalendarNotFoundError
from db.models.enums import GoogleCalendarStatus
from db.queries.daily import (
    GoogleEventValues,
    delete_missing_google_events,
    lock_calendar_connection,
    select_connected_calendar_user_ids,
    upsert_google_events,
)
from services.daily_clock import load_daily_clock
from services.daily_events import MAX_EVENT_NOTES_LENGTH, MAX_EVENT_TITLE_LENGTH
from services.distributed_lock import LockNotAcquiredError, acquire_lock
from services.errors import AppError, ConflictError, ExternalServiceError
from services.google_calendar import access_token_for, complete_authorization, get_connection
from services.tracker_day import ONE_DAY, day_of

if TYPE_CHECKING:
    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncSession

    from clients.google_calendar import GoogleCalendarClient, GoogleCalendarEvent
    from db.models.daily import GoogleCalendarConnection
    from services.daily_clock import DailyClock

logger = get_logger("calendar_sync")

SYNC_LOCK_TTL_SECONDS = 5 * 60
UNTITLED_EVENT = "(без названия)"
_LOCK_KEY = "lock:calendar:sync:{user_id}"
_SYNC_BUSY = "Календарь уже синхронизируется — обновите страницу через минуту"
_CALENDARS_MISSING = "Календари недоступны в Google: {calendars} — снимите их в профиле"
# Событие, закончившееся ровно в начале дня, этот день не занимает.
_END_EPSILON = timedelta(microseconds=1)


@dataclass(slots=True)
class CalendarEvents:
    """События окна по выбранным календарям и календари, которых у аккаунта больше нет."""

    values: list[GoogleEventValues] = field(default_factory=list)
    missing_calendars: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class SyncResult:
    synced: bool
    events: int = 0


def _event_days(event: GoogleCalendarEvent, clock: DailyClock) -> tuple[date, date] | None:
    if event.starts_at is not None:
        day = day_of(event.starts_at, clock.day_start)
        if event.ends_at is None or event.ends_at <= event.starts_at:
            return day, day
        return day, max(day, day_of(event.ends_at - _END_EPSILON, clock.day_start))
    if event.start_date is None:
        return None
    end_day = event.end_date - ONE_DAY if event.end_date else event.start_date
    return event.start_date, max(event.start_date, end_day)


def event_values(
    event: GoogleCalendarEvent,
    *,
    calendar_id: str,
    clock: DailyClock,
) -> GoogleEventValues | None:
    days = _event_days(event, clock)
    if days is None:
        return None
    notes = event.description[:MAX_EVENT_NOTES_LENGTH] if event.description else None
    return GoogleEventValues(
        calendar_id=calendar_id,
        external_id=event.id,
        day=days[0],
        end_day=days[1],
        starts_at=event.starts_at,
        ends_at=event.ends_at,
        title=(event.summary or UNTITLED_EVENT)[:MAX_EVENT_TITLE_LENGTH],
        notes=notes,
    )


async def _calendar_events(
    client: GoogleCalendarClient,
    *,
    access_token: str,
    connection: GoogleCalendarConnection,
    clock: DailyClock,
) -> CalendarEvents:
    window = clock.window
    time_min = clock.bounds(window.first_history_day)[0]
    time_max = clock.bounds(window.tomorrow)[1]
    fetched = CalendarEvents()
    for calendar_id in connection.calendar_ids:
        try:
            events = await client.list_events(
                access_token=access_token,
                calendar_id=calendar_id,
                time_min=time_min,
                time_max=time_max,
            )
        except CalendarNotFoundError:
            # Удалённый календарь не останавливает остальные; его события
            # уходят из «Дейли» как исчезнувшие.
            fetched.missing_calendars.append(calendar_id)
            continue
        for event in events:
            value = event_values(event, calendar_id=calendar_id, clock=clock)
            if value is not None:
                fetched.values.append(value)
    return fetched


async def _sync_connection(
    db_session: AsyncSession,
    client: GoogleCalendarClient,
    *,
    connection: GoogleCalendarConnection,
    now: datetime,
) -> SyncResult:
    access_token = await access_token_for(db_session, client, connection=connection)
    if access_token is None:
        return SyncResult(synced=False)
    clock = await load_daily_clock(db_session, now=now)
    try:
        fetched = await _calendar_events(
            client,
            access_token=access_token,
            connection=connection,
            clock=clock,
        )
    except ExternalServiceError as exc:
        connection.last_error = exc.message
        await db_session.commit()
        raise
    values = fetched.values
    user_id, email = connection.user_id, connection.google_email
    # Пока шёл запрос к Google, календарь могли отключить или войти другим
    # аккаунтом — тогда события этого запроса устарели.
    current = await lock_calendar_connection(db_session, user_id=user_id)
    if (
        current is None
        or current.google_email != email
        or current.status is not GoogleCalendarStatus.CONNECTED
    ):
        await db_session.rollback()
        logger.info("google_calendar_sync_outdated", user_id=str(user_id))
        return SyncResult(synced=False)
    await upsert_google_events(db_session, user_id=connection.user_id, events=values)
    await delete_missing_google_events(
        db_session,
        user_id=connection.user_id,
        first_day=clock.window.first_history_day,
        last_day=clock.window.tomorrow,
        kept=[(value.calendar_id, value.external_id) for value in values],
    )
    connection.last_synced_at = now
    connection.last_error = (
        _CALENDARS_MISSING.format(calendars=", ".join(fetched.missing_calendars))
        if fetched.missing_calendars
        else None
    )
    await db_session.commit()
    logger.info("google_calendar_synced", user_id=str(connection.user_id), events=len(values))
    return SyncResult(synced=True, events=len(values))


async def sync_user_calendar(
    db_session: AsyncSession,
    redis_client: Redis,
    client: GoogleCalendarClient,
    *,
    user_id: uuid.UUID,
    now: datetime,
) -> SyncResult:
    """Синхронизация, которая уже идёт, — `ConflictError` (кнопка «Обновить»)."""
    try:
        async with acquire_lock(
            redis_client,
            _LOCK_KEY.format(user_id=user_id),
            ttl_seconds=SYNC_LOCK_TTL_SECONDS,
            busy_message=_SYNC_BUSY,
        ):
            connection = await get_connection(db_session, user_id=user_id)
            if connection is None or connection.status is not GoogleCalendarStatus.CONNECTED:
                return SyncResult(synced=False)
            return await _sync_connection(db_session, client, connection=connection, now=now)
    except LockNotAcquiredError as exc:
        raise ConflictError(_SYNC_BUSY) from exc


async def sync_all_calendars(
    db_session: AsyncSession,
    redis_client: Redis,
    client: GoogleCalendarClient,
    *,
    now: datetime,
) -> int:
    """
    Периодическая синхронизация: сбой или занятая синхронизация одного
    пользователя не останавливает остальных. Возвращает число синхронизированных.
    """
    synced = 0
    for user_id in await select_connected_calendar_user_ids(db_session):
        try:
            result = await sync_user_calendar(
                db_session,
                redis_client,
                client,
                user_id=user_id,
                now=now,
            )
        except (ExternalServiceError, ConflictError) as exc:
            await db_session.rollback()
            logger.warning("google_calendar_sync_skipped", user_id=str(user_id), reason=exc.message)
            continue
        synced += int(result.synced)
    return synced


async def complete_login(
    db_session: AsyncSession,
    redis_client: Redis,
    client: GoogleCalendarClient,
    *,
    state: str,
    code: str,
    now: datetime,
) -> None:
    """
    Возврат из Google после входа: подключение и первая синхронизация. Сбой
    входа — `AppError`; сбой первой синхронизации вход не отменяет —
    периодическая задача повторит её.
    """
    account = await complete_authorization(
        db_session,
        redis_client,
        client,
        state=state,
        code=code,
    )
    try:
        await sync_user_calendar(db_session, redis_client, client, user_id=account.user_id, now=now)
    except AppError as exc:
        await db_session.rollback()
        logger.warning("google_calendar_first_sync_failed", reason=exc.message)
