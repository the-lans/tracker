"""
Запросы привязок репозиториев к задаче (раздел 3.2 ТЗ) без бизнес-решений и
коммита — их принимает `services/task_repositories.py`.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import sqlalchemy as sa

from db.models.tasks import Task, TaskRepository

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def lock_task_row(db_session: AsyncSession, task_id: uuid.UUID) -> None:
    """Строка задачи под блокировкой до коммита; объект в сессии перечитывается."""
    stmt = sa.select(Task).where(Task.id == task_id).with_for_update()
    await db_session.execute(stmt.execution_options(populate_existing=True))


async def select_attached_repository_ids(
    db_session: AsyncSession,
    task_id: uuid.UUID,
) -> set[uuid.UUID]:
    stmt = sa.select(TaskRepository.repository_id).where(TaskRepository.task_id == task_id)
    return set(await db_session.scalars(stmt))
