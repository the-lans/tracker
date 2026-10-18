import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.enums import PeriodicRunStatus, PeriodicScheduleType, UserRole
from db.models.periodic import PeriodicTask
from db.models.users import User
from services.errors import ValidationError
from services.periodic_tasks import (
    compute_next_run_at,
    list_enabled_periodic_tasks,
    record_periodic_task_run,
)


async def _make_user(db_session: AsyncSession) -> User:
    user = User(email=f"{uuid.uuid4()}@example.com", role=UserRole.ADMIN)
    db_session.add(user)
    await db_session.flush()
    return user


def _make_interval_task(
    *,
    name: str,
    is_enabled: bool = True,
    interval_seconds: int = 300,
) -> PeriodicTask:
    return PeriodicTask(
        name=name,
        display_name=name,
        description="d",
        task_path=f"tasks.periodic.{name}",
        schedule_type=PeriodicScheduleType.INTERVAL,
        interval_seconds=interval_seconds,
        is_enabled=is_enabled,
    )


def _make_crontab_task(*, name: str, crontab_expression: str = "*/10 * * * *") -> PeriodicTask:
    return PeriodicTask(
        name=name,
        display_name=name,
        description="d",
        task_path=f"tasks.periodic.{name}",
        schedule_type=PeriodicScheduleType.CRONTAB,
        crontab_expression=crontab_expression,
        is_enabled=True,
    )


async def test_list_enabled_periodic_tasks_excludes_disabled(db_session: AsyncSession) -> None:
    user = await _make_user(db_session)
    enabled = _make_interval_task(name=f"enabled-{uuid.uuid4().hex[:6]}")
    disabled = _make_interval_task(name=f"disabled-{uuid.uuid4().hex[:6]}", is_enabled=False)
    enabled.updated_by = user.id
    disabled.updated_by = user.id
    db_session.add_all([enabled, disabled])
    await db_session.flush()

    found = await list_enabled_periodic_tasks(db_session)

    found_names = {task.name for task in found}
    assert enabled.name in found_names
    assert disabled.name not in found_names


def test_compute_next_run_at_interval() -> None:
    task = _make_interval_task(name="x", interval_seconds=300)
    now = datetime(2026, 1, 1, tzinfo=UTC)

    next_run = compute_next_run_at(task, now=now)

    assert next_run == now + timedelta(seconds=300)


def test_compute_next_run_at_crontab() -> None:
    task = _make_crontab_task(name="x", crontab_expression="0 * * * *")  # каждый час
    now = datetime(2026, 1, 1, 10, 15, tzinfo=UTC)

    next_run = compute_next_run_at(task, now=now)

    assert next_run == datetime(2026, 1, 1, 11, 0, tzinfo=UTC)


def test_compute_next_run_at_raises_when_interval_missing() -> None:
    task = _make_interval_task(name="x")
    task.interval_seconds = None

    with pytest.raises(ValidationError):
        compute_next_run_at(task, now=datetime.now(UTC))


def test_compute_next_run_at_raises_when_crontab_missing() -> None:
    task = _make_crontab_task(name="x")
    task.crontab_expression = None

    with pytest.raises(ValidationError):
        compute_next_run_at(task, now=datetime.now(UTC))


async def test_record_periodic_task_run_updates_fields(db_session: AsyncSession) -> None:
    user = await _make_user(db_session)
    task = _make_interval_task(name=f"x-{uuid.uuid4().hex[:6]}", interval_seconds=60)
    task.updated_by = user.id
    db_session.add(task)
    await db_session.flush()
    ran_at = datetime(2026, 1, 1, tzinfo=UTC)

    await record_periodic_task_run(
        db_session,
        periodic_task=task,
        status=PeriodicRunStatus.SUCCESS,
        ran_at=ran_at,
    )

    assert task.last_run_at == ran_at
    assert task.last_run_status is PeriodicRunStatus.SUCCESS
    assert task.next_run_at == ran_at + timedelta(seconds=60)
