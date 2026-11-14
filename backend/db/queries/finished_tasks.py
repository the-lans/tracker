"""
Кандидаты проходов по завершённым задачам (разделы 6.4, 14.2, 14.3 ТЗ):
архивация, очистка репозиториев, удаление истории сессии и артефактов.
"""

from __future__ import annotations

import uuid
from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

import sqlalchemy as sa

from db.models.enums import TaskStatus
from db.models.tasks import Task
from db.models.users import RETENTION_FOREVER, User

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.orm import InstrumentedAttribute

    type CleanedAtColumn = InstrumentedAttribute[datetime | None]

ONE_DAY = sa.text("interval '1 day'")


@dataclass(frozen=True, slots=True)
class FinishedTask:
    """
    Снимок кандидата прохода. Не ORM-объект: откат пропущенной задачи
    просрочил бы объекты остальных, а их чтение в async-сессии упало бы.
    """

    id: uuid.UUID
    status: TaskStatus


def _not_cleaned(cleaned_at: CleanedAtColumn | None) -> list[sa.ColumnElement[bool]]:
    return [] if cleaned_at is None else [cleaned_at.is_(None)]


async def _select_finished_tasks(
    db_session: AsyncSession,
    *conditions: sa.ColumnElement[bool],
) -> list[FinishedTask]:
    stmt = (
        sa.select(Task.id, Task.status)
        .join(User, User.id == Task.created_by)
        .where(*conditions)
        .order_by(Task.finished_at, Task.id)
    )
    rows = await db_session.execute(stmt)
    return [FinishedTask(id=task_id, status=status) for task_id, status in rows]


async def select_tasks_past_author_term(
    db_session: AsyncSession,
    *,
    statuses: Collection[TaskStatus],
    term_days: InstrumentedAttribute[int],
    now: datetime,
    cleaned_at: CleanedAtColumn | None = None,
) -> list[FinishedTask]:
    """
    Задачи в `statuses`, у которых от завершения прошёл срок автора
    `term_days` (`RETENTION_FOREVER` — срок выключен); с `cleaned_at` —
    только ещё не очищенные.
    """
    return await _select_finished_tasks(
        db_session,
        Task.status.in_(statuses),
        term_days != RETENTION_FOREVER,
        Task.finished_at < now - term_days * ONE_DAY,
        *_not_cleaned(cleaned_at),
    )


async def select_archived_before(
    db_session: AsyncSession,
    *,
    cutoff: datetime,
    cleaned_at: CleanedAtColumn,
) -> list[FinishedTask]:
    """
    Задачи, лежащие в `archived` с момента раньше `cutoff` и ещё не очищенные.
    """
    return await _select_finished_tasks(
        db_session,
        Task.status == TaskStatus.ARCHIVED,
        Task.archived_at < cutoff,
        *_not_cleaned(cleaned_at),
    )
