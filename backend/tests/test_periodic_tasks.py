import uuid
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.enums import PeriodicRunStatus, PeriodicScheduleType, UserRole
from db.models.logs import AppLog
from db.models.periodic import PeriodicTask
from db.models.users import User
from db.session import async_session_factory
from services.errors import ValidationError
from services.periodic_tasks import (
    compute_next_run_at,
    list_enabled_periodic_tasks,
    record_periodic_task_run,
)
from tasks.periodic import _run_periodic_async
from tests.factories import make_user


async def _make_user(db_session: AsyncSession) -> User:
    return await make_user(db_session, role=UserRole.ADMIN)


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


class TestRunningStatus:
    """
    Раздел 3.1, 15.5: пока тело периодической задачи выполняется, её статус —
    `running`, потом — итог запуска. Обёртка коммитит своей сессией, поэтому
    запись удаляется вручную.
    """

    @pytest.mark.parametrize(
        ("fails", "final"),
        [(False, PeriodicRunStatus.SUCCESS), (True, PeriodicRunStatus.FAILED)],
        ids=["success", "failure"],
    )
    async def test_status_during_run(
        self,
        run_migrations: None,
        fails: bool,
        final: PeriodicRunStatus,
    ) -> None:
        name = f"probe-{uuid.uuid4().hex[:8]}"
        async with async_session_factory() as session:
            session.add(_make_interval_task(name=name))
            await session.commit()
        seen: list[PeriodicRunStatus | None] = []

        async def body(db_session: AsyncSession) -> None:
            status = await db_session.scalar(
                sa.select(PeriodicTask.last_run_status).where(PeriodicTask.name == name),
            )
            seen.append(status)
            if fails:
                raise RuntimeError("сбой периодической задачи")

        try:
            await _run_periodic_async(name, body)
            async with async_session_factory() as session:
                stored = await session.scalar(
                    sa.select(PeriodicTask.last_run_status).where(PeriodicTask.name == name),
                )
        finally:
            async with async_session_factory() as session:
                await session.execute(sa.delete(AppLog).where(AppLog.source == f"periodic.{name}"))
                await session.execute(sa.delete(PeriodicTask).where(PeriodicTask.name == name))
                await session.commit()

        assert seen == [PeriodicRunStatus.RUNNING]
        assert stored is final
