"""`api/monitoring.py` — раздел 15.5, 17.2 ТЗ."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

from db.models.enums import AppLogLevel
from db.models.logs import AppLog

if TYPE_CHECKING:
    from httpx import AsyncClient


async def test_filters_by_level(admin_client: AsyncClient, db_session: AsyncSession) -> None:
    db_session.add_all(
        [
            AppLog(level=AppLogLevel.ERROR, source="tasks.periodic", message="упало", context={}),
            AppLog(level=AppLogLevel.INFO, source="tasks.periodic", message="ок", context={}),
        ],
    )
    await db_session.flush()

    response = await admin_client.get("/app-logs", params={"level": AppLogLevel.ERROR.value})

    assert response.status_code == 200
    entries = response.json()
    assert all(entry["level"] == AppLogLevel.ERROR.value for entry in entries)
    assert any(entry["message"] == "упало" for entry in entries)


async def test_non_admin_cannot_view_app_logs(authed_client: AsyncClient) -> None:
    response = await authed_client.get("/app-logs")

    assert response.status_code == 403
