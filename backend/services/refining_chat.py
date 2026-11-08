"""
Чат с агентом в «Уточняется» (раздел 14.4 ТЗ).

Ручные запросы задачи в `refining` выполняет воркер сессий в режиме чата: без
пайплайна и без смены статуса. Пока воркер ведёт чат, у задачи стоит
`chat_active` — в том числе когда агент ждёт ответа (`awaiting_input`,
`plan_review`). По этому признаку сбой воркера возвращает задачу в
`refining`, а не в `failed`.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import sqlalchemy as sa

from app_logging.config import get_logger
from db.models.enums import ManualRequestStatus, TaskStatus
from db.models.prompts import TaskManualRequestQueue
from db.models.tasks import Task
from services.errors import ConflictError
from services.task_status import (
    REFINING_DECISION_STATUSES,
    close_turn_after_error,
    transition_task_status,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger("refining_chat")

CHAT_BUSY_MESSAGE = "Дождитесь окончания ответа агента"


class ChatLostError(RuntimeError):
    """Воркер, ведший чат задачи, перестал подавать пульс (раздел 6.6)."""


async def start_chat(db_session: AsyncSession, *, task_id: uuid.UUID) -> Task | None:
    """
    Воркер уже владеет сессией (пульс). `None` — задача ушла из `refining`,
    пока сообщение ждало воркера: чат не начинается.

    Запуск — ручной: без галочки «Занимать слот» чат слот не занимает и тогда,
    когда агент ждёт ответа (раздел 14.4).
    """
    updated = await db_session.execute(
        sa.update(Task)
        .where(Task.id == task_id, Task.status == TaskStatus.REFINING)
        .values(chat_active=True, launched_manually=True)
        .returning(Task.id),
    )
    if updated.scalar_one_or_none() is None:
        await db_session.rollback()
        logger.info("refining_chat_not_started", task_id=str(task_id))
        return None
    await db_session.commit()
    return await db_session.get(Task, task_id, populate_existing=True)


async def finish_chat(db_session: AsyncSession, *, task_id: uuid.UUID) -> None:
    await db_session.execute(sa.update(Task).where(Task.id == task_id).values(chat_active=False))
    await db_session.commit()


async def settle_chat_after_error(
    db_session: AsyncSession,
    *,
    task_id: uuid.UUID,
    error: BaseException,
) -> None:
    """
    Раздел 14.4: сбой сессии в чате закрывает запрос с ошибкой и оставляет
    задачу в `refining` — из ожидания ответа она туда возвращается.
    """
    await close_turn_after_error(db_session, task_id=task_id, error=error)
    task = await db_session.get(Task, task_id, populate_existing=True)
    if task is not None and task.status in REFINING_DECISION_STATUSES:
        try:
            await transition_task_status(
                db_session,
                task_id=task_id,
                from_status=task.status,
                to_status=TaskStatus.REFINING,
            )
        except ConflictError:
            logger.info("refining_chat_status_changed_concurrently", task_id=str(task_id))
    await finish_chat(db_session, task_id=task_id)


async def recover_lost_chat(db_session: AsyncSession, *, task_id: uuid.UUID) -> None:
    """Раздел 6.6: чат больше никто не ведёт — как при его сбое."""
    logger.warning("refining_chat_lost", task_id=str(task_id))
    await settle_chat_after_error(
        db_session,
        task_id=task_id,
        error=ChatLostError("воркер чата перестал отвечать"),
    )


async def chat_has_pending_requests(db_session: AsyncSession, *, task_id: uuid.UUID) -> bool:
    """
    Сообщение пришло, когда воркер уже выходил из чата: его ждёт новый
    проход воркера, иначе запрос остался бы в очереди без исполнителя.
    """
    pending = await db_session.scalar(
        sa.select(TaskManualRequestQueue.id)
        .join(Task, Task.id == TaskManualRequestQueue.task_id)
        .where(
            TaskManualRequestQueue.task_id == task_id,
            TaskManualRequestQueue.status == ManualRequestStatus.QUEUED,
            Task.status == TaskStatus.REFINING,
        )
        .limit(1),
    )
    return pending is not None
