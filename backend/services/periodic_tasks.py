"""Динамическое расписание периодических задач (раздел 16.1, 16.3 ТЗ).

Расписание хранится в таблице `periodic_tasks`, не хардкодится — Celery
Beat (кастомный scheduler, `tasks/periodic_scheduler.py`) читает записи
через `list_enabled_periodic_tasks` на каждом тике, подхватывая изменения
без перезапуска процесса (раздел 16.1).

`record_periodic_task_run` — единая точка обновления `last_run_at`/
`last_run_status`/`next_run_at` (раздел 16.3), вызывается из обёртки
Celery-таска (`tasks/periodic.py`) вне зависимости от исхода — успеха или
исключения (раздел 16.3: "ошибка выполнения периодической задачи не
должна приводить к падению процесса Celery Beat").
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import TYPE_CHECKING

import sqlalchemy as sa
from croniter import croniter

from app_logging.config import get_logger
from db.models.enums import PeriodicRunStatus, PeriodicScheduleType
from db.models.periodic import PeriodicTask
from services.errors import ValidationError

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger("periodic_tasks")


async def list_enabled_periodic_tasks(db_session: AsyncSession) -> list[PeriodicTask]:
    stmt = sa.select(PeriodicTask).where(PeriodicTask.is_enabled == True)  # noqa: E712
    return list((await db_session.execute(stmt)).scalars().all())


CRONTAB_FIELD_COUNT = 5


def validate_crontab_expression(expression: str) -> str:
    """
    Стандартный 5-польный cron (`минута час день_месяца месяц день_недели`):
    его понимают и Celery Beat, и расчёт `next_run_at`.
    """
    normalized = " ".join(expression.split())
    if len(normalized.split()) != CRONTAB_FIELD_COUNT or not croniter.is_valid(normalized):
        raise ValidationError(
            "Расписание cron — 5 полей «минута час день_месяца месяц день_недели», "
            f"например «0 3 * * *»; получено {expression!r}",
        )
    return normalized


async def update_periodic_task(
    db_session: AsyncSession,
    *,
    periodic_task: PeriodicTask,
    interval_seconds: int | None,
    crontab_expression: str | None,
    is_enabled: bool | None,
    updated_by: uuid.UUID,
) -> PeriodicTask:
    """
    Раздел 15.5, 16.1: расписание меняется из админки без деплоя — Beat
    подхватит его при следующем чтении таблицы. Тип расписания задачи не
    меняется, поэтому применимо только поле её типа.
    """
    if interval_seconds is not None:
        if periodic_task.schedule_type is not PeriodicScheduleType.INTERVAL:
            raise ValidationError(
                f"Задача {periodic_task.name} использует {periodic_task.schedule_type}, "
                "а не interval — interval_seconds не применим",
            )
        periodic_task.interval_seconds = interval_seconds
    if crontab_expression is not None:
        if periodic_task.schedule_type is not PeriodicScheduleType.CRONTAB:
            raise ValidationError(
                f"Задача {periodic_task.name} использует {periodic_task.schedule_type}, "
                "а не crontab — crontab_expression не применим",
            )
        periodic_task.crontab_expression = validate_crontab_expression(crontab_expression)
    if is_enabled is not None:
        periodic_task.is_enabled = is_enabled
    periodic_task.updated_by = updated_by
    await db_session.commit()
    await db_session.refresh(periodic_task)
    return periodic_task


def compute_next_run_at(periodic_task: PeriodicTask, *, now: datetime) -> datetime:
    """Раздел 16.3: `next_run_at` вычисляется после каждого запуска."""
    if periodic_task.schedule_type is PeriodicScheduleType.INTERVAL:
        if periodic_task.interval_seconds is None:
            raise ValidationError(
                f"Периодическая задача {periodic_task.name}: interval_seconds не задан",
            )
        return now + timedelta(seconds=periodic_task.interval_seconds)

    if periodic_task.crontab_expression is None:
        raise ValidationError(
            f"Периодическая задача {periodic_task.name}: crontab_expression не задан",
        )
    return croniter(periodic_task.crontab_expression, now).get_next(ret_type=type(now))  # type: ignore[no-any-return]


async def mark_periodic_task_running(
    db_session: AsyncSession,
    *,
    periodic_task: PeriodicTask,
) -> None:
    """Раздел 3.1, 15.5: пока задача выполняется, её статус — `running`."""
    periodic_task.last_run_status = PeriodicRunStatus.RUNNING
    await db_session.commit()


async def record_periodic_task_run(
    db_session: AsyncSession,
    *,
    periodic_task: PeriodicTask,
    status: PeriodicRunStatus,
    ran_at: datetime,
) -> None:
    periodic_task.last_run_at = ran_at
    periodic_task.last_run_status = status
    periodic_task.next_run_at = compute_next_run_at(periodic_task, now=ran_at)
    await db_session.commit()
    logger.info(
        "periodic_task_run_recorded",
        name=periodic_task.name,
        status=status,
        next_run_at=periodic_task.next_run_at,
    )
