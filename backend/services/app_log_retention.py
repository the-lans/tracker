"""
Срок хранения журнала `app_logs` (раздел 17.2 ТЗ): записи старше
`system_settings.app_logs_retention_days` удаляются периодической задачей
`purge_old_app_logs` раз в день (раздел 16.2); 0 — журнал хранится бессрочно.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from db.models.users import RETENTION_FOREVER
from db.queries.app_logs import delete_app_logs_before

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def purge_old_app_logs(db_session: AsyncSession, *, now: datetime, days: int) -> int:
    if days == RETENTION_FOREVER:
        return 0
    deleted = await delete_app_logs_before(db_session, now - timedelta(days=days))
    await db_session.commit()
    return deleted
