"""
Сроки хранения данных архивной задачи (разделы 6.4, 14.3 ТЗ).

История сессии (`CLAUDE_SESSIONS_ROOT/<код>`) удаляется у задачи, которая в
архиве дольше `ARCHIVED_SESSION_RETENTION_DAYS`; артефакты
(`user_files/<код>`) — через срок автора `users.artifacts_retention_days` от
завершения задачи (0 — бессрочно). Оба прохода — периодические задачи раз в
час (раздел 16.2) на общем каркасе `services/task_passes.py`; отметка об
удалении исключает задачу из следующих проходов.

Пока сессия задачи пересказывает историю для дочерней задачи, удаление
откладывается до следующего прохода. Новый прогон задачи сбрасывает отметки
(`task_status._finish_values`).
"""

from __future__ import annotations

from abc import abstractmethod
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, ClassVar

from app_logging.config import get_logger
from db.models.enums import TaskStatus
from db.models.tasks import Task
from db.models.users import User
from db.queries.finished_tasks import (
    FinishedTask,
    select_archived_before,
    select_tasks_past_author_term,
)
from db.queries.parent_summaries import summary_in_progress
from services.errors import ConflictError
from services.session_context import forget_task_session
from services.task_codes import validate_task_code
from services.task_passes import TaskPass, remove_directory
from services.task_status import lock_task

if TYPE_CHECKING:
    from pathlib import Path

    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger("task_retention")

SESSIONS_LOCK_KEY = "lock:cleanup_archived_task_sessions"
ARTIFACTS_LOCK_KEY = "lock:cleanup_archived_task_artifacts"
ARCHIVED_SESSION_RETENTION_DAYS = 180
_ARCHIVED_STATUSES = (TaskStatus.ARCHIVED,)


class ArchivedTaskDataPass(TaskPass):
    """Удаляет каталог задачи в `root` и ставит отметку об удалении."""

    removed_event: ClassVar[str]

    def __init__(self, db_session: AsyncSession, *, now: datetime, root: Path) -> None:
        super().__init__(db_session, now=now)
        self.root = root

    @abstractmethod
    def mark_removed(self, task: Task) -> None:
        """Отметка об удалении в строке задачи; коммитит проход."""

    async def handle(self, task: FinishedTask) -> bool:
        try:
            locked = await self._lock_archived(task)
        except ConflictError as exc:
            return await self.skip(task.id, exc)
        directory = self.root / validate_task_code(locked.code)
        await remove_directory(directory)
        self.mark_removed(locked)
        await self.db_session.commit()
        logger.info(self.removed_event, task_id=str(task.id), path=str(directory))
        return True

    async def _lock_archived(self, task: FinishedTask) -> Task:
        """
        Строка задачи до коммита; задача ушла из архива или занята — `ConflictError`.
        """
        locked = await lock_task(self.db_session, task.id)
        if locked is None or locked.status is not TaskStatus.ARCHIVED:
            raise ConflictError("Задача уже не в архиве")
        if await summary_in_progress(self.db_session, locked.id):
            raise ConflictError("Сессия задачи пересказывает историю для дочерней задачи")
        return locked


class SessionHistoryPass(ArchivedTaskDataPass):
    """
    История сессии задачи, лежащей в архиве дольше 180 дней, удаляется как
    «Очистить контекст»: новый прогон после «Вернуть в новые» начнёт новую сессию.
    """

    lock_key = SESSIONS_LOCK_KEY
    busy_message = "Удаление истории сессий уже выполняется"
    skipped_event = "task_session_cleanup_skipped"
    removed_event = "task_session_history_removed"

    async def candidates(self) -> list[FinishedTask]:
        return await select_archived_before(
            self.db_session,
            cutoff=self.now - timedelta(days=ARCHIVED_SESSION_RETENTION_DAYS),
            cleaned_at=Task.session_cleaned_at,
        )

    def mark_removed(self, task: Task) -> None:
        forget_task_session(task)
        task.session_cleaned_at = self.now


class ArtifactsPass(ArchivedTaskDataPass):
    """
    Артефакты архивной задачи удаляются через `users.artifacts_retention_days`.
    """

    lock_key = ARTIFACTS_LOCK_KEY
    busy_message = "Удаление артефактов уже выполняется"
    skipped_event = "task_artifacts_cleanup_skipped"
    removed_event = "task_artifacts_removed"

    async def candidates(self) -> list[FinishedTask]:
        return await select_tasks_past_author_term(
            self.db_session,
            statuses=_ARCHIVED_STATUSES,
            term_days=User.artifacts_retention_days,
            now=self.now,
            cleaned_at=Task.artifacts_cleaned_at,
        )

    def mark_removed(self, task: Task) -> None:
        task.artifacts_cleaned_at = self.now
