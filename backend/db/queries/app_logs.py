"""Журнал приложения `app_logs` (раздел 17.2 ТЗ)."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

import sqlalchemy as sa

from db.models.logs import AppLog

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def delete_app_logs_before(db_session: AsyncSession, cutoff: datetime) -> int:
    """
    Удаляет записи старше `cutoff` (индекс `ix_app_logs_created_at`); число удалённых.
    """
    result = await db_session.execute(sa.delete(AppLog).where(AppLog.created_at < cutoff))
    return int(result.rowcount)  # type: ignore[attr-defined]
