"""
История выполнения нод задачи — источник ``{{node.*}}`` (раздел 5 ТЗ) для
нод пайплайна и промтов библиотеки.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import sqlalchemy as sa

from db.models.logs import NodeLog

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def load_node_log_history(db_session: AsyncSession, task_id: uuid.UUID) -> list[NodeLog]:
    """Записи ``node_logs`` задачи в хронологическом порядке."""
    # План и ответы пользователя пишет callback разрешений в своей сессии БД;
    # без перечитывания здесь остались бы прежние значения (`expire_on_commit`
    # выключен) и `{{node.plan_text}}`/`{{node.user_input}}` пришли бы пустыми.
    stmt = (
        sa.select(NodeLog)
        .where(NodeLog.task_id == task_id)
        .order_by(NodeLog.started_at, NodeLog.id)
        .execution_options(populate_existing=True)
    )
    return list((await db_session.execute(stmt)).scalars().all())
