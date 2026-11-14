"""
Очистка рабочей директории репозиториев (раздел 14.2, 14.3 ТЗ, правило 5):
кнопкой «Очистить репозитории» или по сроку автора (`services/task_archive.py`).

Удаляется корень задачи в volume `task_repos` — клоны репозиториев, файлы
шаблонов и профили MCP-инструментов (раздел 10.3). Пользовательские файлы
задачи живут в отдельном volume `user_files` и сюда не входят (раздел 14.3).
Перезапуск задачи из `failed` после очистки склонирует репозитории заново
(`services/task_workspace.py::prepare_task_workspace`).

Пока сессия задачи пересказывает историю для дочерней задачи (ответвление
сессии работает в её директории, `services/parent_summary.py`), очистка
запрещена.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from app_logging.config import get_logger
from db.models.tasks import Task
from db.queries.parent_summaries import summary_in_progress
from services.errors import ConflictError
from services.task_passes import remove_directory
from services.task_status import FINISHED_STATUSES, lock_task
from services.task_workspace import task_root

if TYPE_CHECKING:
    from pathlib import Path

    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger("task_cleanup")

# Раздел 14.3: только завершённый прогон (в том числе в архиве) — у задачи
# нет живой сессии.
CLEANABLE_STATUSES = FINISHED_STATUSES


async def cleanup_task_repositories(
    db_session: AsyncSession,
    *,
    task: Task,
    repos_root: Path,
) -> None:
    """
    Удаляет рабочую директорию задачи и отмечает `tasks.repo_cleaned_at`.

    Повторный вызов безопасен: отсутствующая директория — не ошибка.
    """
    # Строка задачи блокируется до коммита: «Перезапустить» ставит воркер в
    # очередь, не меняя статус, — его захват (`UPDATE ... WHERE status`)
    # дождётся конца очистки, и клонирование не пойдёт параллельно с удалением.
    locked = await lock_task(db_session, task.id)
    if locked is None or locked.status not in CLEANABLE_STATUSES:
        raise ConflictError("Очистить репозитории можно только у завершённой или упавшей задачи")
    if await summary_in_progress(db_session, locked.id):
        raise ConflictError(
            "Сессия задачи сейчас пересказывает историю для дочерней задачи — "
            "очистите репозитории после того, как пересказ будет готов",
        )
    root = task_root(repos_root, task)
    await remove_directory(root)
    task.repo_cleaned_at = datetime.now(UTC)
    await db_session.commit()
    logger.info("task_repositories_cleaned", task_id=str(task.id), path=str(root))
