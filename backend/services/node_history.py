"""
История выполнения нод задачи — источник ``{{node.*}}`` (раздел 5 ТЗ) для
нод пайплайна и промтов библиотеки, лента и вкладка «Логи» (раздел 13.4).
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import sqlalchemy as sa

from db.models.enums import NodeLogStatus, NodeLogTriggerType
from db.models.logs import NodeLog

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def load_node_log_history(db_session: AsyncSession, task_id: uuid.UUID) -> list[NodeLog]:
    """Записи ``node_logs`` задачи в хронологическом порядке."""
    # План и ответы пользователя пишет callback разрешений в своей сессии БД;
    # без перечитывания здесь остались бы прежние значения (`expire_on_commit`
    # выключен) и `{{node.plan_text}}`/`{{node.user_input}}` пришли бы пустыми.
    stmt = _history_stmt(task_id).execution_options(populate_existing=True)
    return list((await db_session.execute(stmt)).scalars().all())


async def filter_node_logs(
    db_session: AsyncSession,
    task_id: uuid.UUID,
    *,
    node_id: uuid.UUID | None = None,
    status: NodeLogStatus | None = None,
    trigger_type: NodeLogTriggerType | None = None,
) -> list[NodeLog]:
    """Записи ``node_logs`` задачи по фильтрам ноды, статуса и источника (``None`` — любой)."""
    stmt = _history_stmt(task_id)
    filters = {NodeLog.node_id: node_id, NodeLog.status: status, NodeLog.trigger_type: trigger_type}
    for column, value in filters.items():
        if value is not None:
            stmt = stmt.where(column == value)
    return list((await db_session.execute(stmt)).scalars().all())


def _history_stmt(task_id: uuid.UUID) -> sa.Select[NodeLog]:
    return (
        sa.select(NodeLog)
        .where(NodeLog.task_id == task_id)
        .order_by(NodeLog.started_at, NodeLog.id)
    )
