"""Ручная очистка рабочей директории репозиториев (раздел 14.2, 14.3 ТЗ, правило 5).

Удаляется корень задачи в volume `task_repos` — клоны репозиториев, файлы
шаблонов и профили MCP-инструментов (раздел 10.3). Пользовательские файлы
задачи живут в отдельном volume `user_files` и сюда не входят (раздел 14.3).
Перезапуск задачи из `failed` после очистки склонирует репозитории заново
(`services/task_workspace.py::prepare_task_workspace`).
"""

from __future__ import annotations

import asyncio
import shutil
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import sqlalchemy as sa

from app_logging.config import get_logger
from db.models.enums import TaskStatus
from db.models.tasks import Task
from services.errors import ConflictError
from services.task_workspace import task_root

if TYPE_CHECKING:
    from pathlib import Path

    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger("task_cleanup")

# Раздел 14.3: только терминальные статусы — у задачи нет живой сессии.
CLEANABLE_STATUSES = frozenset({TaskStatus.DONE, TaskStatus.FAILED})


async def cleanup_task_repositories(
    db_session: AsyncSession,
    *,
    task: Task,
    repos_root: Path,
) -> None:
    """Удаляет рабочую директорию задачи и отмечает `tasks.repo_cleaned_at`.

    Повторный вызов безопасен: отсутствующая директория — не ошибка.
    """
    # Строка задачи блокируется до коммита: «Перезапустить» ставит воркер в
    # очередь, не меняя статус, — его захват (`UPDATE ... WHERE status`)
    # дождётся конца очистки, и клонирование не пойдёт параллельно с удалением.
    locked = await db_session.scalar(
        sa.select(Task)
        .where(Task.id == task.id)
        .with_for_update()
        .execution_options(populate_existing=True),
    )
    if locked is None or locked.status not in CLEANABLE_STATUSES:
        raise ConflictError("Очистить репозитории можно только у завершённой или упавшей задачи")
    root = task_root(repos_root, task)
    await asyncio.to_thread(shutil.rmtree, root, ignore_errors=True)
    task.repo_cleaned_at = datetime.now(UTC)
    await db_session.commit()
    logger.info("task_repositories_cleaned", task_id=str(task.id), path=str(root))
