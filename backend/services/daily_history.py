"""
История дня «Дейли» (раздел 15.8 ТЗ): задачи, отмеченные на день, с тем, что
по ним было сделано за этот день, и события дня.

Работа по задаче за день — нода или ручной запрос начались или закончились
в границах дня трекера, либо задача завершилась в этот день. Будущий день
факта не имеет.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from db.models.enums import TaskStatus
from db.queries.daily import (
    MarkedTaskRow,
    select_day_events,
    select_marked_tasks,
    select_previous_active_day,
    select_worked_task_ids,
)
from services.tracker_day import ensure_in_history

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from db.models.daily import DailyEvent
    from db.models.users import User
    from services.daily_clock import DailyClock


class DayFact(StrEnum):
    """Что было по отмеченной задаче за день."""

    DONE = "done"
    FAILED = "failed"
    WORKED = "worked"
    NO_WORK = "no_work"


@dataclass(frozen=True, slots=True)
class MarkedTask:
    id: uuid.UUID
    code: str
    title: str
    status: TaskStatus
    # None — день ещё не наступил.
    fact: DayFact | None


@dataclass(frozen=True, slots=True)
class DayView:
    day: date
    tasks: list[MarkedTask]
    events: list[DailyEvent]


@dataclass(frozen=True, slots=True)
class PreviousDay:
    """
    Прошлый день для плана: последний день до сегодняшнего с отметками или
    событиями, и задачи, отмеченные на него, по которым в нём была работа.
    """

    day: date | None
    done: list[MarkedTask]
    events: list[DailyEvent]


def _finished_as(row: MarkedTaskRow) -> TaskStatus:
    if row.status is TaskStatus.ARCHIVED and row.archived_from_status is not None:
        return row.archived_from_status
    return row.status


def day_fact(row: MarkedTaskRow, *, worked: bool, start: datetime, end: datetime) -> DayFact:
    if row.finished_at is not None and start <= row.finished_at < end:
        return DayFact.FAILED if _finished_as(row) is TaskStatus.FAILED else DayFact.DONE
    return DayFact.WORKED if worked else DayFact.NO_WORK


async def _marked_with_facts(
    db_session: AsyncSession,
    *,
    user: User,
    day: date,
    clock: DailyClock,
) -> list[MarkedTask]:
    rows = await select_marked_tasks(db_session, user_id=user.id, day=day)
    if day > clock.window.today:
        return [MarkedTask(row.id, row.code, row.title, row.status, None) for row in rows]
    start, end = clock.bounds(day)
    worked = await select_worked_task_ids(
        db_session,
        task_ids=[row.id for row in rows],
        start=start,
        end=end,
    )
    return [
        MarkedTask(
            row.id,
            row.code,
            row.title,
            row.status,
            day_fact(row, worked=row.id in worked, start=start, end=end),
        )
        for row in rows
    ]


async def day_view(
    db_session: AsyncSession,
    *,
    user: User,
    day: date,
    clock: DailyClock,
    include_hidden: bool,
) -> DayView:
    return DayView(
        day=day,
        tasks=await _marked_with_facts(db_session, user=user, day=day, clock=clock),
        events=await select_day_events(
            db_session,
            user_id=user.id,
            day=day,
            include_hidden=include_hidden,
        ),
    )


async def history_day_view(
    db_session: AsyncSession,
    *,
    user: User,
    day: date,
    clock: DailyClock,
) -> DayView:
    """День вкладки «История»: только дни окна, вместе со скрытыми событиями."""
    ensure_in_history(clock.window, day)
    return await day_view(db_session, user=user, day=day, clock=clock, include_hidden=True)


async def previous_day(
    db_session: AsyncSession,
    *,
    user: User,
    before: date,
    clock: DailyClock,
) -> PreviousDay:
    day = await select_previous_active_day(db_session, user_id=user.id, before=before)
    if day is None:
        return PreviousDay(day=None, done=[], events=[])
    view = await day_view(db_session, user=user, day=day, clock=clock, include_hidden=False)
    done = [task for task in view.tasks if task.fact not in (None, DayFact.NO_WORK)]
    return PreviousDay(day=day, done=done, events=view.events)
