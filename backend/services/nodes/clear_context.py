"""Guard ноды `clear_context` (раздел 11.5 ТЗ, правило 6 CLAUDE.md).

Очистка контекста сессии запрещена, пока существует хотя бы одна запись
`node_logs` со статусом `running`/`awaiting_decision` — обрывать сессию
посреди незавершённого обмена репликами означает потерять его результат
без возможности восстановления.
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.enums import NodeLogStatus
from db.models.logs import NodeLog
from services.errors import ConflictError

_BLOCKING_STATUSES = (NodeLogStatus.RUNNING, NodeLogStatus.AWAITING_DECISION)


async def ensure_clear_context_allowed(db_session: AsyncSession, task_id: uuid.UUID) -> None:
    stmt = (
        sa.select(NodeLog.id)
        .where(NodeLog.task_id == task_id, NodeLog.status.in_(_BLOCKING_STATUSES))
        .limit(1)
    )
    if (await db_session.execute(stmt)).first() is not None:
        raise ConflictError(
            "Нельзя очистить контекст сессии: есть незавершённые записи "
            "node_logs (running/awaiting_decision)",
        )
