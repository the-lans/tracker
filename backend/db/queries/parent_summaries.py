"""Пересказы истории родительской задачи для дочерних (раздел 6.7 ТЗ)."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import sqlalchemy as sa

from db.models.enums import ParentSummaryStatus, TaskStatus
from db.models.tasks import Task, TaskParentSummary

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def summary_in_progress(db_session: AsyncSession, parent_task_id: uuid.UUID) -> bool:
    """
    Пересказ для дочерней задачи ещё может выполняться: он работает в
    директории задачи и читает историю её сессии.

    Запись `pending` у остановленной дочерней задачи не в счёт: её воркер
    пересказ уже не ждёт, и иначе данные родителя было бы не очистить никогда.
    """
    stmt = (
        sa.select(TaskParentSummary.id)
        .join(Task, Task.id == TaskParentSummary.child_task_id)
        .where(
            TaskParentSummary.parent_task_id == parent_task_id,
            TaskParentSummary.status == ParentSummaryStatus.PENDING,
            Task.status == TaskStatus.IN_PROGRESS,
        )
        .limit(1)
    )
    return (await db_session.execute(stmt)).first() is not None
