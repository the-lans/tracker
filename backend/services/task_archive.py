"""
Архив задач (раздел 14.2 ТЗ): уход завершённой задачи в `archived` через N
дней автора, очистка её репозиториев через M дней и выборка раздела «Архив».

Сроки отсчитываются от `tasks.finished_at` — перехода в `done`/`failed`.
Оба прохода — периодические задачи раз в час (раздел 16.2); каждый идёт под
распределённой блокировкой, а изменение задачи — compare-and-swap статуса или
блокировка строки, поэтому повторный запуск ничего не делает дважды.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

import sqlalchemy as sa

from app_logging.config import get_logger
from db.models.categories import TaskCategory
from db.models.enums import TaskStatus
from db.models.tasks import Task
from db.models.users import User
from services.access import owner_filter
from services.distributed_lock import LockNotAcquiredError, acquire_lock
from services.errors import ConflictError, ValidationError
from services.task_cleanup import cleanup_task_repositories
from services.task_status import FINAL_STATUSES, FINISHED_STATUSES, transition_task_status

if TYPE_CHECKING:
    from pathlib import Path

    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.orm import InstrumentedAttribute

logger = get_logger("task_archive")

ARCHIVE_LOCK_KEY = "lock:archive_finished_tasks"
CLEANUP_LOCK_KEY = "lock:cleanup_finished_task_repositories"
# Проход идёт раз в час: блокировка живёт чуть меньше интервала.
PASS_LOCK_TTL_SECONDS = 55 * 60
_ONE_DAY = sa.text("interval '1 day'")

# Раздел 15.1: страница архива.
DEFAULT_ARCHIVE_PAGE_SIZE = 20
MAX_ARCHIVE_PAGE_SIZE = 100
MAX_ARCHIVE_SEARCH_LENGTH = 200


@dataclass(slots=True)
class PassResult:
    """Итог прохода: какие задачи изменены, какие пропущены до следующего часа."""

    done: list[uuid.UUID] = field(default_factory=list)
    skipped: list[uuid.UUID] = field(default_factory=list)
    lock_busy: bool = False


@dataclass(frozen=True, slots=True)
class FinishedTask:
    """
    Снимок кандидата прохода. Не ORM-объект: откат пропущенной задачи
    просрочил бы объекты остальных, а их чтение в async-сессии упало бы.
    """

    id: uuid.UUID
    status: TaskStatus


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


def _finished_before(
    days: InstrumentedAttribute[int | None],
    now: datetime,
) -> sa.ColumnElement[bool]:
    """
    Срок автора прошёл. NULL у автора — срок выключен: разность с NULL тоже
    NULL, и условие ложно без отдельной проверки.
    """
    return Task.finished_at < now - days * _ONE_DAY


async def _finished_tasks(
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


async def find_tasks_to_archive(db_session: AsyncSession, *, now: datetime) -> list[FinishedTask]:
    return await _finished_tasks(
        db_session,
        Task.status.in_(FINAL_STATUSES),
        _finished_before(User.archive_after_days, now),
    )


async def archive_task(db_session: AsyncSession, *, task: FinishedTask, now: datetime) -> bool:
    """False — статус успел смениться (перезапуск, возврат в статус до запуска)."""
    final_status = task.status
    try:
        await transition_task_status(
            db_session,
            task_id=task.id,
            from_status=final_status,
            to_status=TaskStatus.ARCHIVED,
            extra_values={"archived_at": now, "archived_from_status": final_status},
        )
    except ConflictError:
        await db_session.rollback()
        logger.info("task_archive_skipped", task_id=str(task.id), status=final_status)
        return False
    logger.info("task_archived", task_id=str(task.id), from_status=final_status)
    return True


async def find_tasks_to_clean(db_session: AsyncSession, *, now: datetime) -> list[FinishedTask]:
    return await _finished_tasks(
        db_session,
        Task.status.in_(FINISHED_STATUSES),
        Task.repo_cleaned_at.is_(None),
        _finished_before(User.cleanup_repos_after_days, now),
    )


async def clean_task(db_session: AsyncSession, *, task_id: uuid.UUID, repos_root: Path) -> bool:
    """
    Очистка — тем же кодом, что и кнопка (раздел 14.3). False — задача занята
    (пересказ для дочерней задачи, новый прогон): повтор через час.
    """
    task = await db_session.get(Task, task_id, populate_existing=True)
    if task is None:
        return False
    try:
        await cleanup_task_repositories(db_session, task=task, repos_root=repos_root)
    except ConflictError as exc:
        await db_session.rollback()
        # После отката объект задачи просрочен — id берётся из аргумента.
        logger.info("task_repositories_cleanup_skipped", task_id=str(task_id), reason=str(exc))
        return False
    return True


async def archive_finished_tasks(
    db_session: AsyncSession,
    redis_client: Redis,
    *,
    now: datetime,
) -> PassResult:
    result = PassResult()
    try:
        async with acquire_lock(
            redis_client,
            ARCHIVE_LOCK_KEY,
            ttl_seconds=PASS_LOCK_TTL_SECONDS,
            busy_message="Архивация задач уже выполняется",
        ):
            for task in await find_tasks_to_archive(db_session, now=now):
                archived = await archive_task(db_session, task=task, now=now)
                (result.done if archived else result.skipped).append(task.id)
    except LockNotAcquiredError:
        logger.info("task_archive_already_running")
        result.lock_busy = True
    return result


async def clean_finished_task_repositories(
    db_session: AsyncSession,
    redis_client: Redis,
    *,
    now: datetime,
    repos_root: Path,
) -> PassResult:
    result = PassResult()
    try:
        async with acquire_lock(
            redis_client,
            CLEANUP_LOCK_KEY,
            ttl_seconds=PASS_LOCK_TTL_SECONDS,
            busy_message="Очистка репозиториев уже выполняется",
        ):
            for task in await find_tasks_to_clean(db_session, now=now):
                cleaned = await clean_task(db_session, task_id=task.id, repos_root=repos_root)
                (result.done if cleaned else result.skipped).append(task.id)
    except LockNotAcquiredError:
        logger.info("task_repositories_cleanup_already_running")
        result.lock_busy = True
    return result


def _archive_conditions(user: User, filters: ArchiveFilters) -> list[sa.ColumnElement[bool]]:
    if (
        filters.finished_from is not None
        and filters.finished_to is not None
        and filters.finished_from > filters.finished_to
    ):
        raise ValidationError("Начало периода позже его конца")
    conditions = [Task.status == TaskStatus.ARCHIVED, owner_filter(Task.created_by, user)]
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


async def list_archived_tasks(
    db_session: AsyncSession,
    *,
    user: User,
    filters: ArchiveFilters,
    page: int,
    page_size: int,
) -> ArchivePage:
    """Раздел 15.1 «Архив»: свои задачи (администратору — все), новые сверху."""
    conditions = _archive_conditions(user, filters)
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
