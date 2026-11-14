"""
Срок хранения журнала `app_logs` (раздел 17.2): старые записи удаляются, 0 — бессрочно.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa

from db.models.enums import AppLogLevel
from db.models.logs import AppLog
from db.models.users import RETENTION_FOREVER
from services.app_log_retention import purge_old_app_logs

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.ext.asyncio import AsyncSession

NOW = datetime(2026, 11, 14, 12, 0, tzinfo=UTC)


async def _app_log(db_session: AsyncSession, *, age: timedelta) -> uuid.UUID:
    app_log = AppLog(
        level=AppLogLevel.INFO,
        source="tests",
        message="запись",
        context={},
        created_at=NOW - age,
    )
    db_session.add(app_log)
    await db_session.flush()
    return app_log.id


async def _kept(db_session: AsyncSession, ids: list[uuid.UUID]) -> list[bool]:
    remaining = set(
        (await db_session.execute(sa.select(AppLog.id).where(AppLog.id.in_(ids)))).scalars(),
    )
    return [item in remaining for item in ids]


class TestPurgeOldAppLogs:
    @pytest.mark.parametrize(
        ("age", "kept"),
        [
            (timedelta(days=31), False),
            (timedelta(days=30, seconds=1), False),
            (timedelta(days=30), True),
            (timedelta(days=1), True),
        ],
        ids=["old", "just_over", "boundary", "recent"],
    )
    async def test_threshold(
        self,
        db_session: AsyncSession,
        age: timedelta,
        kept: bool,
    ) -> None:
        app_log_id = await _app_log(db_session, age=age)

        await purge_old_app_logs(db_session, now=NOW, days=30)

        assert await _kept(db_session, [app_log_id]) == [kept]

    async def test_forever_keeps_everything(self, db_session: AsyncSession) -> None:
        app_log_id = await _app_log(db_session, age=timedelta(days=4000))

        deleted = await purge_old_app_logs(db_session, now=NOW, days=RETENTION_FOREVER)

        assert deleted == 0
        assert await _kept(db_session, [app_log_id]) == [True]
