"""
Архив задач (раздел 14.2 ТЗ): уход завершённой задачи в `archived` через N
дней автора, очистка её репозиториев через M дней и выборка раздела «Архив».

Сроки отсчитываются от `tasks.finished_at` — перехода в `done`/`failed`;
0 у автора — срок выключен. Оба прохода — периодические задачи раз в час
(раздел 16.2) на общем каркасе `services/task_passes.py`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app_logging.config import get_logger
from db.models.enums import TaskStatus
from db.models.tasks import Task
from db.models.users import User
from db.queries.archived_tasks import ArchiveFilters, ArchivePage, select_archive_page
from db.queries.finished_tasks import FinishedTask, select_tasks_past_author_term
from services.access import is_admin
from services.errors import ConflictError, ValidationError
from services.task_cleanup import cleanup_task_repositories
from services.task_passes import TaskPass
from services.task_status import FINAL_STATUSES, FINISHED_STATUSES, transition_task_status

if TYPE_CHECKING:
    from datetime import datetime
    from pathlib import Path

    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "ARCHIVE_LOCK_KEY",
    "CLEANUP_LOCK_KEY",
    "DEFAULT_ARCHIVE_PAGE_SIZE",
    "MAX_ARCHIVE_PAGE_SIZE",
    "MAX_ARCHIVE_SEARCH_LENGTH",
    "ArchiveFilters",
    "ArchivePage",
    "ArchivePass",
    "RepositoryCleanupPass",
    "list_archived_tasks",
]

logger = get_logger("task_archive")

ARCHIVE_LOCK_KEY = "lock:archive_finished_tasks"
CLEANUP_LOCK_KEY = "lock:cleanup_finished_task_repositories"

# Раздел 15.1: страница архива.
DEFAULT_ARCHIVE_PAGE_SIZE = 20
MAX_ARCHIVE_PAGE_SIZE = 100
MAX_ARCHIVE_SEARCH_LENGTH = 200


class ArchivePass(TaskPass):
    """
    Задачи в `done`/`failed` старше `users.archive_after_days` уходят в `archived`.
    """

    lock_key = ARCHIVE_LOCK_KEY
    busy_message = "Архивация задач уже выполняется"
    skipped_event = "task_archive_skipped"

    async def candidates(self) -> list[FinishedTask]:
        return await select_tasks_past_author_term(
            self.db_session,
            statuses=FINAL_STATUSES,
            term_days=User.archive_after_days,
            now=self.now,
        )

    async def handle(self, task: FinishedTask) -> bool:
        """
        False — статус успел смениться (перезапуск, возврат в статус до запуска).
        """
        try:
            await transition_task_status(
                self.db_session,
                task_id=task.id,
                from_status=task.status,
                to_status=TaskStatus.ARCHIVED,
                extra_values={"archived_at": self.now, "archived_from_status": task.status},
            )
        except ConflictError as exc:
            return await self.skip(task.id, exc)
        logger.info("task_archived", task_id=str(task.id), from_status=task.status)
        return True


class RepositoryCleanupPass(TaskPass):
    """
    Репозитории задач в `done`, `failed`, `archived` очищаются через
    `users.cleanup_repos_after_days` — тем же кодом, что и кнопка (раздел 14.3).
    """

    lock_key = CLEANUP_LOCK_KEY
    busy_message = "Очистка репозиториев уже выполняется"
    skipped_event = "task_repositories_cleanup_skipped"

    def __init__(self, db_session: AsyncSession, *, now: datetime, repos_root: Path) -> None:
        super().__init__(db_session, now=now)
        self.repos_root = repos_root

    async def candidates(self) -> list[FinishedTask]:
        return await select_tasks_past_author_term(
            self.db_session,
            statuses=FINISHED_STATUSES,
            term_days=User.cleanup_repos_after_days,
            now=self.now,
            cleaned_at=Task.repo_cleaned_at,
        )

    async def handle(self, task: FinishedTask) -> bool:
        """
        False — задача занята (пересказ для дочерней задачи, новый прогон).
        """
        record = await self.db_session.get(Task, task.id, populate_existing=True)
        if record is None:
            return False
        try:
            await cleanup_task_repositories(
                self.db_session,
                task=record,
                repos_root=self.repos_root,
            )
        except ConflictError as exc:
            return await self.skip(task.id, exc)
        return True


def _validate_filters(filters: ArchiveFilters) -> None:
    if (
        filters.finished_from is not None
        and filters.finished_to is not None
        and filters.finished_from > filters.finished_to
    ):
        raise ValidationError("Начало периода позже его конца")


async def list_archived_tasks(
    db_session: AsyncSession,
    *,
    user: User,
    filters: ArchiveFilters,
    page: int,
    page_size: int,
) -> ArchivePage:
    """Раздел 15.1 «Архив»: свои задачи (администратору — все), новые сверху."""
    _validate_filters(filters)
    return await select_archive_page(
        db_session,
        owner_id=None if is_admin(user) else user.id,
        filters=filters,
        page=page,
        page_size=page_size,
    )
