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
