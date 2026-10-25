"""Автоматический запуск задачи по расписанию (раздел 12 ТЗ).

Периодическая задача `check_scheduled_tasks_for_autostart` (раздел 16.2,
регистрация в Celery Beat — этап 11 плана реализации) каждые 5 минут
вызывает `run_scheduled_autostart_check`. Идемпотентность (раздел 12.2,
п. 3) обеспечивает `transition_task_status`'s compare-and-swap: как только
задача переходит `new -> queued`, повторный проход в том же окне её больше
не находит (она уже не в `new`).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import sqlalchemy as sa

from app_logging.config import get_logger
from db.models.enums import AppLogLevel, TaskStatus
from db.models.logs import AppLog
from db.models.tasks import Task
from services.errors import ConflictError, ValidationError
from services.notifications import NotificationEvent, notify_task_event
from services.task_launch import ensure_task_launchable
from services.task_status import transition_task_status

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger("autostart")


async def find_tasks_due_for_autostart(db_session: AsyncSession, *, now: datetime) -> list[Task]:
    """Раздел 12.2, п. 1."""
    stmt = sa.select(Task).where(
        Task.status == TaskStatus.NEW,
        Task.auto_start_enabled == True,  # noqa: E712 — sa.Boolean-колонка, не Python bool
        Task.scheduled_start_at.is_not(None),
        Task.scheduled_start_at <= now,
    )
    return list((await db_session.execute(stmt)).scalars().all())


@dataclass(frozen=True, slots=True)
class AutostartBatchResult:
    started_task_ids: list[uuid.UUID] = field(default_factory=list)
    failed_task_ids: list[uuid.UUID] = field(default_factory=list)


async def run_scheduled_autostart_check(
    db_session: AsyncSession,
    *,
    now: datetime,
) -> AutostartBatchResult:
    """Раздел 12.2 (п. 2), 12.3: ошибка одной задачи не прерывает пачку.

    "Тот же процесс запуска, что и ручная кнопка «Выполнить»" (12.2, п. 2)
    здесь — переход `new -> queued`; фактический запуск пайплайна
    (Celery-таск, владеющий сессией) инициируется отдельно, вне этой
    функции — раздел 12.2 описывает именно постановку в очередь как
    "тот же процесс", а не синхронное выполнение всего пайплайна.
    """
    tasks = await find_tasks_due_for_autostart(db_session, now=now)
    result = AutostartBatchResult()
    for task in tasks:
        try:
            await ensure_task_launchable(db_session, task)
            await transition_task_status(
                db_session,
                task_id=task.id,
                from_status=TaskStatus.NEW,
                to_status=TaskStatus.QUEUED,
            )
            result.started_task_ids.append(task.id)
            logger.info("task_autostarted", task_id=str(task.id))
        except (ValidationError, ConflictError) as exc:
            result.failed_task_ids.append(task.id)
            logger.error("task_autostart_failed", task_id=str(task.id), error=str(exc))
            db_session.add(
                AppLog(
                    level=AppLogLevel.ERROR,
                    source="autostart",
                    message=f"Не удалось автоматически запустить задачу: {exc}",
                    context={"task_id": str(task.id)},
                    task_id=task.id,
                ),
            )
            await db_session.commit()
            await notify_task_event(
                db_session,
                event=NotificationEvent.AUTOSTART_FAILED,
                task=task,
                detail=f"{task.code}: не удалось запустить по расписанию — {exc}",
            )
    return result
