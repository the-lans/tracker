"""Динамический планировщик Celery Beat (раздел 16.1 ТЗ).

Переопределяет `Scheduler.get_schedule()`, читающийся `tick()` на каждой
итерации: правки расписания в `periodic_tasks` (административный
интерфейс, раздел 15.5) подхватываются без перезапуска процесса Beat —
именно то, что требует раздел 16.1. Опрос БД кэшируется на
``_REFRESH_INTERVAL_SECONDS``, чтобы не выполнять его на каждый (частый)
тик планировщика.

Запуск: ``celery -A tasks.celery_app beat -l info -S tasks.periodic_scheduler.DatabaseScheduler``.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from celery import schedules
from celery.beat import ScheduleEntry, Scheduler

from app_logging.config import get_logger
from db.models.enums import PeriodicScheduleType
from db.session import async_session_factory
from services.periodic_tasks import list_enabled_periodic_tasks
from tasks.async_runner import run_with_fresh_pool

if TYPE_CHECKING:
    from db.models.periodic import PeriodicTask

logger = get_logger("periodic_scheduler")

_REFRESH_INTERVAL_SECONDS = 10.0
_CRONTAB_FIELD_COUNT = 5


def parse_crontab_expression(expression: str) -> tuple[str, str, str, str, str]:
    """Стандартный 5-польный cron (`минута час день_месяца месяц день_недели`)."""
    parts = expression.split()
    if len(parts) != _CRONTAB_FIELD_COUNT:
        message = f"crontab_expression должен состоять из 5 полей: {expression!r}"
        raise ValueError(message)
    minute, hour, day_of_month, month_of_year, day_of_week = parts
    return minute, hour, day_of_month, month_of_year, day_of_week


def celery_schedule_for(periodic_task: PeriodicTask) -> schedules.BaseSchedule:
    if periodic_task.schedule_type is PeriodicScheduleType.INTERVAL:
        if periodic_task.interval_seconds is None:
            message = f"{periodic_task.name}: interval_seconds не задан"
            raise ValueError(message)
        return schedules.schedule(run_every=periodic_task.interval_seconds)

    if periodic_task.crontab_expression is None:
        message = f"{periodic_task.name}: crontab_expression не задан"
        raise ValueError(message)
    minute, hour, day_of_month, month_of_year, day_of_week = parse_crontab_expression(
        periodic_task.crontab_expression,
    )
    return schedules.crontab(
        minute=minute,
        hour=hour,
        day_of_month=day_of_month,
        month_of_year=month_of_year,
        day_of_week=day_of_week,
    )


class DatabaseScheduler(Scheduler):  # type: ignore[misc]  # celery без py.typed
    """Раздел 16.1: динамический источник расписания из таблицы `periodic_tasks`."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._last_refresh = 0.0
        self._cached_schedule: dict[str, ScheduleEntry] = {}
        super().__init__(*args, **kwargs)

    def get_schedule(self) -> dict[str, ScheduleEntry]:
        now = time.monotonic()
        if now - self._last_refresh >= _REFRESH_INTERVAL_SECONDS or not self._cached_schedule:
            self._cached_schedule = self._load_schedule_from_db()
            self._last_refresh = now
        return self._cached_schedule

    def set_schedule(self, schedule: dict[str, ScheduleEntry]) -> None:
        self._cached_schedule = schedule

    schedule = property(get_schedule, set_schedule)

    def _load_schedule_from_db(self) -> dict[str, ScheduleEntry]:
        try:
            periodic_tasks = run_with_fresh_pool(_fetch_enabled_periodic_tasks())
        except Exception as exc:  # noqa: BLE001 — сбой обновления расписания не должен ронять Beat
            logger.error("periodic_schedule_refresh_failed", error=str(exc))
            return self._cached_schedule

        entries: dict[str, ScheduleEntry] = {}
        for periodic_task in periodic_tasks:
            try:
                entries[periodic_task.name] = ScheduleEntry(
                    name=periodic_task.name,
                    task=periodic_task.name,
                    schedule=celery_schedule_for(periodic_task),
                    app=self.app,
                )
            except ValueError as exc:
                logger.error(
                    "periodic_schedule_entry_invalid",
                    name=periodic_task.name,
                    error=str(exc),
                )
        return entries


async def _fetch_enabled_periodic_tasks() -> list[PeriodicTask]:
    async with async_session_factory() as db_session:
        return await list_enabled_periodic_tasks(db_session)
