"""Ручная очистка контекста сессии (раздел 14.2, 11.5, 22 ТЗ, правило 6).

Кнопка доступна в `failed`: живой сессии у задачи нет, поэтому сбросить её
— значит забыть `tasks.session_id`. «Перезапустить с текущей ноды» тогда
откроет новую сессию (`services/session_lifecycle.py::plan_session_start`,
вместе с мостом `/remote-control`), а её `session_id` сохранится после
первого же ответа — как и при ноде `clear_context`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app_logging.config import get_logger
from db.models.enums import TaskStatus
from services.errors import ConflictError
from services.nodes.clear_context import ensure_clear_context_allowed

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from db.models.tasks import Task

logger = get_logger("session_context")


async def clear_task_session_context(db_session: AsyncSession, *, task: Task) -> None:
    if task.status is not TaskStatus.FAILED:
        raise ConflictError("Очистить контекст можно только у задачи в статусе failed")
    await ensure_clear_context_allowed(db_session, task.id)
    previous_session_id = task.session_id
    task.session_id = None
    await db_session.commit()
    logger.info(
        "task_session_context_cleared",
        task_id=str(task.id),
        previous_session_id=previous_session_id,
    )
