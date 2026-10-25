"""`api/periodic_tasks.py` — раздел 15.5, 16.1 ТЗ."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.enums import PeriodicScheduleType
from db.models.periodic import PeriodicTask
from db.models.users import User

if TYPE_CHECKING:
    from httpx import AsyncClient


async def _create_periodic_task(
    db_session: AsyncSession,
    admin: User,
    *,
    schedule_type: PeriodicScheduleType = PeriodicScheduleType.INTERVAL,
    interval_seconds: int | None = 300,
    crontab_expression: str | None = None,
) -> PeriodicTask:
    periodic_task = PeriodicTask(
        id=uuid.uuid4(),
        name=f"demo_task_{uuid.uuid4().hex[:8]}",
        display_name="Демо-задача",
        description="",
        task_path="tasks.periodic.demo_task",
        schedule_type=schedule_type,
        interval_seconds=interval_seconds,
        crontab_expression=crontab_expression,
        updated_by=admin.id,
    )
    db_session.add(periodic_task)
    await db_session.flush()
    return periodic_task


async def test_update_interval_seconds(
    admin_client: AsyncClient,
    db_session: AsyncSession,
    admin_user: User,
) -> None:
    periodic_task = await _create_periodic_task(db_session, admin_user)

    response = await admin_client.patch(
        f"/periodic-tasks/{periodic_task.id}",
        json={"interval_seconds": 900},
    )

    assert response.status_code == 200
    assert response.json()["interval_seconds"] == 900


async def test_update_crontab_expression_on_interval_task_is_rejected(
    admin_client: AsyncClient,
    db_session: AsyncSession,
    admin_user: User,
) -> None:
    periodic_task = await _create_periodic_task(db_session, admin_user)

    response = await admin_client.patch(
        f"/periodic-tasks/{periodic_task.id}",
        json={"crontab_expression": "*/5 * * * *"},
    )

    assert response.status_code == 422


class TestScheduleValidation:
    """Раздел 16.1: расписание из админки проверяется до сохранения."""

    async def test_crontab_normalized(
        self,
        admin_client: AsyncClient,
        db_session: AsyncSession,
        admin_user: User,
    ) -> None:
        periodic_task = await _create_periodic_task(
            db_session,
            admin_user,
            schedule_type=PeriodicScheduleType.CRONTAB,
            interval_seconds=None,
            crontab_expression="0 3 * * *",
        )

        response = await admin_client.patch(
            f"/periodic-tasks/{periodic_task.id}",
            json={"crontab_expression": "  30  4 * * 1 "},
        )

        assert response.status_code == 200
        assert response.json()["crontab_expression"] == "30 4 * * 1"

    @pytest.mark.parametrize(
        "expression",
        ["0 3 * *", "0 3 * * * *", "61 3 * * *", "каждый день"],
        ids=["four_fields", "six_fields", "bad_minute", "text"],
    )
    async def test_bad_crontab_rejected(
        self,
        admin_client: AsyncClient,
        db_session: AsyncSession,
        admin_user: User,
        expression: str,
    ) -> None:
        periodic_task = await _create_periodic_task(
            db_session,
            admin_user,
            schedule_type=PeriodicScheduleType.CRONTAB,
            interval_seconds=None,
            crontab_expression="0 3 * * *",
        )

        response = await admin_client.patch(
            f"/periodic-tasks/{periodic_task.id}",
            json={"crontab_expression": expression},
        )

        assert response.status_code == 422

    @pytest.mark.parametrize("seconds", [0, -60])
    async def test_non_positive_interval_rejected(
        self,
        admin_client: AsyncClient,
        db_session: AsyncSession,
        admin_user: User,
        seconds: int,
    ) -> None:
        periodic_task = await _create_periodic_task(db_session, admin_user)

        response = await admin_client.patch(
            f"/periodic-tasks/{periodic_task.id}",
            json={"interval_seconds": seconds},
        )

        assert response.status_code == 422


async def test_disable_periodic_task(
    admin_client: AsyncClient,
    db_session: AsyncSession,
    admin_user: User,
) -> None:
    periodic_task = await _create_periodic_task(db_session, admin_user)

    response = await admin_client.patch(
        f"/periodic-tasks/{periodic_task.id}",
        json={"is_enabled": False},
    )

    assert response.status_code == 200
    assert response.json()["is_enabled"] is False


async def test_run_now_sends_celery_task_by_name(
    admin_client: AsyncClient,
    db_session: AsyncSession,
    admin_user: User,
) -> None:
    periodic_task = await _create_periodic_task(db_session, admin_user)

    with patch("api.periodic_tasks.celery_app") as mock_celery_app:
        response = await admin_client.post(f"/periodic-tasks/{periodic_task.id}/run-now")

    assert response.status_code == 202
    mock_celery_app.send_task.assert_called_once_with(periodic_task.name)


async def test_non_admin_cannot_run_periodic_task(
    authed_client: AsyncClient,
    db_session: AsyncSession,
    admin_user: User,
) -> None:
    periodic_task = await _create_periodic_task(db_session, admin_user)

    response = await authed_client.post(f"/periodic-tasks/{periodic_task.id}/run-now")

    assert response.status_code == 403
