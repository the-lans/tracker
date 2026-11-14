"""Выборка раздела «Архив» (раздел 15.1 ТЗ)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

import sqlalchemy as sa

from db.models.categories import TaskCategory
from db.models.enums import TaskStatus
from db.models.tasks import Task

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True, slots=True)
class ArchiveFilters:
    """Отбор раздела «Архив»: поиск по коду и названию, период завершения."""

    search: str | None = None
    finished_from: datetime | None = None
    finished_to: datetime | None = None


@dataclass(frozen=True, slots=True)
class ArchivedTaskRow:
    task: Task
    category_name: str | None


@dataclass(frozen=True, slots=True)
class ArchivePage:
    rows: list[ArchivedTaskRow]
    total: int


def _archive_conditions(
    owner_id: uuid.UUID | None,
    filters: ArchiveFilters,
) -> list[sa.ColumnElement[bool]]:
    conditions: list[sa.ColumnElement[bool]] = [Task.status == TaskStatus.ARCHIVED]
    if owner_id is not None:
        conditions.append(Task.created_by == owner_id)
    search = (filters.search or "").strip()
    if search:
        conditions.append(
            sa.or_(
                Task.code.icontains(search, autoescape=True),
                Task.title.icontains(search, autoescape=True),
            ),
        )
    if filters.finished_from is not None:
        conditions.append(Task.finished_at >= filters.finished_from)
    if filters.finished_to is not None:
        conditions.append(Task.finished_at <= filters.finished_to)
    return conditions


async def select_archive_page(
    db_session: AsyncSession,
    *,
    owner_id: uuid.UUID | None,
    filters: ArchiveFilters,
    page: int,
    page_size: int,
) -> ArchivePage:
    """Архивные задачи автора (`owner_id = None` — всех), новые сверху."""
    conditions = _archive_conditions(owner_id, filters)
    total = await db_session.scalar(sa.select(sa.func.count(Task.id)).where(*conditions))
    stmt = (
        sa.select(Task, TaskCategory.name)
        .outerjoin(TaskCategory, TaskCategory.id == Task.category_id)
        .where(*conditions)
        .order_by(Task.finished_at.desc().nulls_last(), Task.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = [
        ArchivedTaskRow(task=task, category_name=category_name)
        for task, category_name in await db_session.execute(stmt)
    ]
    return ArchivePage(rows=rows, total=total or 0)
