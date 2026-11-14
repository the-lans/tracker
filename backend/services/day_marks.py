"""
Отметки задач по дням (раздел 15.8 ТЗ): пользователь сам отмечает задачу на
сегодня или на завтра. Отметка — только намерение: задачу она не запускает,
а на следующий день не переносится. Отметки личные — у каждого пользователя
свои; отметить можно доступную ему задачу, кроме архивной.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime
from typing import TYPE_CHECKING

from app_logging.config import get_logger
from db.models.enums import TaskStatus
from db.queries.daily import delete_mark, insert_mark, select_mark_days
from services.access import get_task_for_user
from services.daily_clock import load_daily_clock
from services.errors import ConflictError
from services.tracker_day import ensure_markable

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from db.models.users import User

logger = get_logger("day_marks")

_ARCHIVED = "Задачу из архива отметить нельзя"


@dataclass(frozen=True, slots=True)
class TaskDayMarks:
    task_id: uuid.UUID
    days: list[date]


async def set_day_mark(
    db_session: AsyncSession,
    *,
    user: User,
    task_id: uuid.UUID,
    day: date,
    now: datetime,
) -> None:
    clock = await load_daily_clock(db_session, now=now)
    ensure_markable(clock.window, day)
    task = await get_task_for_user(db_session, task_id, user=user)
    if task.status is TaskStatus.ARCHIVED:
        raise ConflictError(_ARCHIVED)
    await insert_mark(db_session, user_id=user.id, task_id=task.id, day=day)
    await db_session.commit()
    logger.info("task_day_marked", task_id=str(task.id), day=day.isoformat())


async def clear_day_mark(
    db_session: AsyncSession,
    *,
    user: User,
    task_id: uuid.UUID,
    day: date,
    now: datetime,
) -> None:
    """Снять можно только отметку сегодняшнего или завтрашнего дня: прошлые дни — история."""
    clock = await load_daily_clock(db_session, now=now)
    ensure_markable(clock.window, day)
    task = await get_task_for_user(db_session, task_id, user=user)
    await delete_mark(db_session, user_id=user.id, task_id=task.id, day=day)
    await db_session.commit()
    logger.info("task_day_unmarked", task_id=str(task.id), day=day.isoformat())


async def recent_day_marks(
    db_session: AsyncSession,
    *,
    user: User,
    now: datetime,
) -> list[TaskDayMarks]:
    """Раздел 15.1: отметки вчера, сегодня и завтра — для фильтра дашборда и задачи."""
    window = (await load_daily_clock(db_session, now=now)).window
    marks = await select_mark_days(
        db_session,
        user_id=user.id,
        days=(window.yesterday, window.today, window.tomorrow),
    )
    return [TaskDayMarks(task_id=task_id, days=days) for task_id, days in marks.items()]
