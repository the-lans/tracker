"""Тесты чистых функций `tasks/periodic_scheduler.py`.

Полноценный прогон `celery.beat.Scheduler.tick()` требует реального
процесса Celery Beat — вне зоны ответственности этого набора тестов
(`tasks/` не входит в порог покрытия 85%, раздел `services/` CLAUDE.md);
здесь проверяется чистая логика построения celery-расписания из строки БД.
"""

from __future__ import annotations

import pytest
from celery import schedules

from db.models.enums import PeriodicScheduleType
from db.models.periodic import PeriodicTask
from tasks.periodic_scheduler import celery_schedule_for, parse_crontab_expression


def _interval_task(seconds: int) -> PeriodicTask:
    return PeriodicTask(
        name="x",
        display_name="x",
        description="d",
        task_path="tasks.periodic.x",
        schedule_type=PeriodicScheduleType.INTERVAL,
        interval_seconds=seconds,
    )


def _crontab_task(expression: str) -> PeriodicTask:
    return PeriodicTask(
        name="x",
        display_name="x",
        description="d",
        task_path="tasks.periodic.x",
        schedule_type=PeriodicScheduleType.CRONTAB,
        crontab_expression=expression,
    )


def test_parse_crontab_expression_splits_five_fields() -> None:
    assert parse_crontab_expression("*/5 * * * *") == ("*/5", "*", "*", "*", "*")


def test_parse_crontab_expression_rejects_wrong_field_count() -> None:
    with pytest.raises(ValueError, match="5 полей"):
        parse_crontab_expression("* * *")


def test_celery_schedule_for_interval_builds_schedule_object() -> None:
    result = celery_schedule_for(_interval_task(300))

    assert isinstance(result, schedules.schedule)
    assert result.run_every.total_seconds() == 300


def test_celery_schedule_for_crontab_builds_crontab_object() -> None:
    result = celery_schedule_for(_crontab_task("0 * * * *"))

    assert isinstance(result, schedules.crontab)


def test_celery_schedule_for_interval_raises_without_interval_seconds() -> None:
    task = _interval_task(300)
    task.interval_seconds = None

    with pytest.raises(ValueError, match="interval_seconds"):
        celery_schedule_for(task)


def test_celery_schedule_for_crontab_raises_without_expression() -> None:
    task = _crontab_task("0 * * * *")
    task.crontab_expression = None

    with pytest.raises(ValueError, match="crontab_expression"):
        celery_schedule_for(task)
