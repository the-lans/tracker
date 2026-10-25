"""
Ручная очистка контекста сессии (раздел 14.2, 11.5, 22 ТЗ, правило 6).

Кнопка доступна в `failed`: живой сессии у задачи нет, поэтому сбросить её
— значит забыть `tasks.session_id`. «Перезапустить с текущей ноды» тогда
откроет новую сессию (`services/session_lifecycle.py::plan_session_start`,
вместе с мостом `/remote-control`), а её `session_id` сохранится после
первого же ответа — как и при ноде `clear_context`.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import sqlalchemy as sa

from app_logging.config import get_logger
from db.models.enums import TaskStatus
from db.models.tasks import Task
from services.errors import ConflictError
from services.nodes.clear_context import ensure_clear_context_allowed
from services.task_status import SESSION_ACTIVE_STATUSES

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger("session_context")


def forget_task_session(task: Task) -> None:
    """
    Следующее обращение начнёт новую сессию; ответы прежней не попадают в
    `{{node.llm_output_last_n}}` (раздел 5).
    """
    task.session_id = None
    task.context_cleared_at = datetime.now(UTC)


async def clear_task_session_context(db_session: AsyncSession, *, task: Task) -> None:
    if task.status is not TaskStatus.FAILED:
        raise ConflictError("Очистить контекст можно только у задачи в статусе failed")
    await ensure_clear_context_allowed(db_session, task.id)
    previous_session_id = task.session_id
    forget_task_session(task)
    await db_session.commit()
    logger.info(
        "task_session_context_cleared",
        task_id=str(task.id),
        previous_session_id=previous_session_id,
    )


async def list_active_sessions(db_session: AsyncSession, *, user_id: uuid.UUID) -> list[Task]:
    """
    Раздел 15.1 (решение 2026-10-20): «активные сессии» профиля — задачи
    пользователя, сессией Claude Code которых сейчас владеет воркер.
    """
    stmt = (
        sa.select(Task)
        .where(Task.created_by == user_id, Task.status.in_(SESSION_ACTIVE_STATUSES))
        .order_by(Task.updated_at.desc())
    )
    return list((await db_session.execute(stmt)).scalars().all())
