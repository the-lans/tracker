"""Автоматический запуск задачи по расписанию (раздел 12 ТЗ).

Периодическая задача `check_scheduled_tasks_for_autostart` и воркер очереди
(раздел 16.2) каждые 5 минут вызывают `run_scheduled_autostart_check`: задача
с наступившим временем встаёт в очередь автора (`ready`, раздел 14.4) и
запускается, когда у автора есть свободный слот. Идемпотентность (раздел
12.2, п. 3) обеспечивает compare-and-swap статуса: задача в очереди под
выборку больше не попадает.
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
from services.errors import ConflictError, ServiceUnavailableError, ValidationError
from services.notifications import NotificationEvent, notify_task_event
from services.task_launch import ensure_task_launchable
from services.task_status import transition_task_status

# Раздел 12.2: в очередь встают задачи до запуска, ещё не стоящие в ней.
AUTOSTART_STATUSES = (TaskStatus.NEW, TaskStatus.REFINING, TaskStatus.DEFINED)

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger("autostart")


async def find_tasks_due_for_autostart(db_session: AsyncSession, *, now: datetime) -> list[Task]:
    """Раздел 12.2, п. 1."""
    stmt = sa.select(Task).where(
        Task.status.in_(AUTOSTART_STATUSES),
        Task.auto_start_enabled == True,  # noqa: E712 — sa.Boolean-колонка, не Python bool
        Task.scheduled_start_at.is_not(None),
        Task.scheduled_start_at <= now,
        # Раздел 14.4: идёт чат в «Уточняется» — задача встанет в очередь после него.
        Task.chat_active == sa.false(),
    )
    return list((await db_session.execute(stmt)).scalars().all())


@dataclass(frozen=True, slots=True)
class AutostartBatchResult:
    queued_task_ids: list[uuid.UUID] = field(default_factory=list)
    failed_task_ids: list[uuid.UUID] = field(default_factory=list)


async def run_scheduled_autostart_check(
    db_session: AsyncSession,
    *,
    now: datetime,
) -> AutostartBatchResult:
    """
    Раздел 12.2 (п. 2), 12.3: ошибка одной задачи не прерывает пачку.

    Проверки — те же, что у «Выполнить»; задача переходит в `ready` с
    выключенным автозапуском, запускает её воркер очереди (раздел 14.4).
    """
    tasks = await find_tasks_due_for_autostart(db_session, now=now)
    result = AutostartBatchResult()
    for task in tasks:
        try:
            await ensure_task_launchable(db_session, task)
            await transition_task_status(
                db_session,
                task_id=task.id,
                from_status=task.status,
                to_status=TaskStatus.READY,
                extra_values={"auto_start_enabled": False},
            )
            result.queued_task_ids.append(task.id)
            logger.info("task_autostart_queued", task_id=str(task.id))
        except ServiceUnavailableError:
            # Раздел 20.6: идёт обновление — задачи остаются в своём статусе и
            # встают в очередь первой проверкой после него, без уведомления о сбое.
            logger.info("task_autostart_deferred_by_maintenance", task_id=str(task.id))
            break
        except (ValidationError, ConflictError) as exc:
            current = await db_session.get(Task, task.id, populate_existing=True)
            if isinstance(exc, ConflictError) and current is not None and current.chat_active:
                logger.info("task_autostart_deferred_by_chat", task_id=str(task.id))
                continue
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
