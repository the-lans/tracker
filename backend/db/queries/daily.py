"""
Запросы «Дейли» (раздел 15.8 ТЗ): отметки задач по дням, работа по задачам
за день, события дня и события Google Calendar (раздел 19.8).
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Collection
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert

from db.models.daily import DailyEvent, DailyPlan, GoogleCalendarConnection, TaskDayMark
from db.models.enums import DailyEventSource, GoogleCalendarStatus, TaskStatus
from db.models.logs import NodeLog
from db.models.tasks import Task

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.orm import InstrumentedAttribute

_ONE_DAY = timedelta(days=1)


@dataclass(frozen=True, slots=True)
class MarkedTaskRow:
    id: uuid.UUID
    code: str
    title: str
    status: TaskStatus
    archived_from_status: TaskStatus | None
    finished_at: datetime | None


@dataclass(frozen=True, slots=True)
class GoogleEventValues:
    """Событие календаря в виде, в котором оно хранится в `daily_events`."""

    calendar_id: str
    external_id: str
    day: date
    end_day: date
    starts_at: datetime | None
    ends_at: datetime | None
    title: str
    notes: str | None


async def insert_mark(
    db_session: AsyncSession,
    *,
    user_id: uuid.UUID,
    task_id: uuid.UUID,
    day: date,
) -> None:
    """Повторная отметка того же дня ничего не меняет."""
    stmt = (
        pg_insert(TaskDayMark)
        .values(id=uuid.uuid4(), user_id=user_id, task_id=task_id, day=day)
        .on_conflict_do_nothing(constraint="uq_task_day_marks_user_task_day")
    )
    await db_session.execute(stmt)


async def delete_mark(
    db_session: AsyncSession,
    *,
    user_id: uuid.UUID,
    task_id: uuid.UUID,
    day: date,
) -> None:
    await db_session.execute(
        sa.delete(TaskDayMark).where(
            TaskDayMark.user_id == user_id,
            TaskDayMark.task_id == task_id,
            TaskDayMark.day == day,
        ),
    )


async def select_mark_days(
    db_session: AsyncSession,
    *,
    user_id: uuid.UUID,
    days: Collection[date],
) -> dict[uuid.UUID, list[date]]:
    """Отметки пользователя на дни `days` по задачам."""
    rows = await db_session.execute(
        sa.select(TaskDayMark.task_id, TaskDayMark.day)
        .where(TaskDayMark.user_id == user_id, TaskDayMark.day.in_(days))
        .order_by(TaskDayMark.task_id, TaskDayMark.day),
    )
    marks: dict[uuid.UUID, list[date]] = defaultdict(list)
    for task_id, day in rows:
        marks[task_id].append(day)
    return dict(marks)


async def select_marked_tasks(
    db_session: AsyncSession,
    *,
    user_id: uuid.UUID,
    day: date,
) -> list[MarkedTaskRow]:
    """Задачи, отмеченные пользователем на день, — в порядке отметки."""
    rows = await db_session.execute(
        sa.select(
            Task.id,
            Task.code,
            Task.title,
            Task.status,
            Task.archived_from_status,
            Task.finished_at,
        )
        .join(TaskDayMark, TaskDayMark.task_id == Task.id)
        .where(TaskDayMark.user_id == user_id, TaskDayMark.day == day)
        .order_by(TaskDayMark.created_at, Task.code),
    )
    return [MarkedTaskRow(*row) for row in rows]


async def select_worked_task_ids(
    db_session: AsyncSession,
    *,
    task_ids: Collection[uuid.UUID],
    start: datetime,
    end: datetime,
) -> set[uuid.UUID]:
    """
    Задачи, по которым в `[start, end)` была работа: нода или ручной запрос
    начались или закончились, либо задача завершилась.
    """
    if not task_ids:
        return set()

    def within(column: InstrumentedAttribute[datetime | None]) -> sa.ColumnElement[bool]:
        return sa.and_(column >= start, column < end)

    node_activity = sa.select(NodeLog.task_id).where(
        NodeLog.task_id.in_(task_ids),
        sa.or_(within(NodeLog.started_at), within(NodeLog.finished_at)),
    )
    finished = sa.select(Task.id).where(Task.id.in_(task_ids), within(Task.finished_at))
    rows = await db_session.execute(sa.union(node_activity, finished))
    return set(rows.scalars())


def _events_of_day(user_id: uuid.UUID, day: date) -> sa.ColumnElement[bool]:
    return sa.and_(DailyEvent.user_id == user_id, DailyEvent.day <= day, DailyEvent.end_day >= day)


async def select_day_events(
    db_session: AsyncSession,
    *,
    user_id: uuid.UUID,
    day: date,
    include_hidden: bool,
) -> list[DailyEvent]:
    """События, занимающие день: без времени — первыми, затем по началу."""
    stmt = (
        sa.select(DailyEvent)
        .where(_events_of_day(user_id, day))
        .order_by(DailyEvent.starts_at.asc().nulls_first(), DailyEvent.title, DailyEvent.id)
    )
    if not include_hidden:
        stmt = stmt.where(DailyEvent.hidden.is_(False))
    return list((await db_session.execute(stmt)).scalars())


async def select_previous_active_day(
    db_session: AsyncSession,
    *,
    user_id: uuid.UUID,
    before: date,
) -> date | None:
    """Последний день до `before` с отметками задач или видимыми событиями."""
    marked = sa.select(sa.func.max(TaskDayMark.day)).where(
        TaskDayMark.user_id == user_id,
        TaskDayMark.day < before,
    )
    last_event_day = sa.func.least(DailyEvent.end_day, before - _ONE_DAY)
    with_events = sa.select(sa.func.max(last_event_day)).where(
        DailyEvent.user_id == user_id,
        DailyEvent.day < before,
        DailyEvent.hidden.is_(False),
    )
    days = [await db_session.scalar(marked), await db_session.scalar(with_events)]
    present = [day for day in days if day is not None]
    return max(present) if present else None


async def select_plan(
    db_session: AsyncSession,
    *,
    user_id: uuid.UUID,
    day: date,
) -> DailyPlan | None:
    result: DailyPlan | None = await db_session.scalar(
        sa.select(DailyPlan).where(DailyPlan.user_id == user_id, DailyPlan.day == day),
    )
    return result


async def select_plans(
    db_session: AsyncSession,
    *,
    user_id: uuid.UUID,
    limit: int,
) -> list[DailyPlan]:
    stmt = (
        sa.select(DailyPlan)
        .where(DailyPlan.user_id == user_id)
        .order_by(DailyPlan.day.desc())
        .limit(limit)
    )
    return list((await db_session.execute(stmt)).scalars())


async def upsert_google_events(
    db_session: AsyncSession,
    *,
    user_id: uuid.UUID,
    events: Collection[GoogleEventValues],
) -> None:
    """
    Событие календаря обновляется по `(calendar_id, external_id)`; отметка
    «скрыто» пользователя при этом сохраняется.
    """
    if not events:
        return
    stmt = pg_insert(DailyEvent).values(
        [
            {
                "id": uuid.uuid4(),
                "user_id": user_id,
                "source": DailyEventSource.GOOGLE,
                "calendar_id": event.calendar_id,
                "external_id": event.external_id,
                "day": event.day,
                "end_day": event.end_day,
                "starts_at": event.starts_at,
                "ends_at": event.ends_at,
                "title": event.title,
                "notes": event.notes,
            }
            for event in events
        ],
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[DailyEvent.user_id, DailyEvent.calendar_id, DailyEvent.external_id],
        index_where=DailyEvent.source == DailyEventSource.GOOGLE,
        set_={
            column: stmt.excluded[column]
            for column in ("day", "end_day", "starts_at", "ends_at", "title", "notes")
        }
        | {"updated_at": sa.func.now()},
    )
    await db_session.execute(stmt)


async def delete_missing_google_events(
    db_session: AsyncSession,
    *,
    user_id: uuid.UUID,
    first_day: date,
    last_day: date,
    kept: Collection[tuple[str, str]],
) -> None:
    """
    Удаляет события календаря окна синхронизации, которых в календаре больше
    нет: удалены, отменены или календарь снят с синхронизации.
    """
    stmt = sa.delete(DailyEvent).where(
        DailyEvent.user_id == user_id,
        DailyEvent.source == DailyEventSource.GOOGLE,
        DailyEvent.day <= last_day,
        DailyEvent.end_day >= first_day,
    )
    if kept:
        stmt = stmt.where(
            sa.tuple_(DailyEvent.calendar_id, DailyEvent.external_id).not_in(list(kept)),
        )
    await db_session.execute(stmt)


async def delete_all_google_events(db_session: AsyncSession, *, user_id: uuid.UUID) -> None:
    await db_session.execute(
        sa.delete(DailyEvent).where(
            DailyEvent.user_id == user_id,
            DailyEvent.source == DailyEventSource.GOOGLE,
        ),
    )


async def lock_calendar_connection(
    db_session: AsyncSession,
    *,
    user_id: uuid.UUID,
) -> GoogleCalendarConnection | None:
    """
    Подключение под `SELECT … FOR UPDATE` с перечитанными полями: синхронизация,
    вход и отключение меняют события календаря по очереди, а не вперемешку.
    """
    stmt = (
        sa.select(GoogleCalendarConnection)
        .where(GoogleCalendarConnection.user_id == user_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    connection: GoogleCalendarConnection | None = await db_session.scalar(stmt)
    return connection


async def select_connected_calendar_user_ids(db_session: AsyncSession) -> list[uuid.UUID]:
    rows = await db_session.execute(
        sa.select(GoogleCalendarConnection.user_id)
        .where(GoogleCalendarConnection.status == GoogleCalendarStatus.CONNECTED)
        .order_by(GoogleCalendarConnection.user_id),
    )
    return list(rows.scalars())


async def swap_calendar_status(
    db_session: AsyncSession,
    *,
    user_id: uuid.UUID,
    expected: GoogleCalendarStatus,
    status: GoogleCalendarStatus,
    last_error: str | None,
) -> bool:
    """Compare-and-swap статуса подключения; `True` — статус сменил этот вызов."""
    result = await db_session.execute(
        sa.update(GoogleCalendarConnection)
        .where(
            GoogleCalendarConnection.user_id == user_id,
            GoogleCalendarConnection.status == expected,
        )
        .values(status=status, last_error=last_error)
        .returning(GoogleCalendarConnection.user_id),
    )
    return result.scalar_one_or_none() is not None
