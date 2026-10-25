"""
История выполнения нод задачи — источник ``{{node.*}}`` (раздел 5 ТЗ) для
нод пайплайна и промтов библиотеки, лента и вкладка «Логи» (раздел 13.4).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

import sqlalchemy as sa

from db.models.enums import NodeLogStatus, NodeLogTriggerType
from db.models.logs import NodeLog

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from db.models.tasks import Task


@dataclass(frozen=True, slots=True)
class NodeContextHistory:
    """
    Источники ``{{node.*}}`` (раздел 5) в хронологическом порядке.

    ``pipeline_runs`` — успешные выполнения нод пайплайна текущего прогона:
    ни неудачная попытка, ни промт библиотеки, ни свободный промт не
    подменяют вывод предыдущей ноды. ``session_replies`` — ответы LLM
    текущей сессии, после последней очистки контекста.
    """

    pipeline_runs: list[NodeLog]
    session_replies: list[str]


EMPTY_NODE_CONTEXT_HISTORY = NodeContextHistory(pipeline_runs=[], session_replies=[])


def _started_since(entry: NodeLog, moment: datetime | None) -> bool:
    return moment is None or (entry.started_at is not None and entry.started_at >= moment)


def _is_current_pipeline_run(entry: NodeLog, task: Task) -> bool:
    return (
        entry.trigger_type is NodeLogTriggerType.PIPELINE
        and entry.status is NodeLogStatus.SUCCESS
        and _started_since(entry, task.reset_at)
    )


async def load_node_context_history(db_session: AsyncSession, task: Task) -> NodeContextHistory:
    """
    История задачи для ``{{node.*}}``: прогон отсчитывается от «Вернуть в
    новые» (`tasks.reset_at`), сессия — от очистки контекста
    (`tasks.context_cleared_at`).
    """
    # План и ответы пользователя пишет callback разрешений в своей сессии БД;
    # без перечитывания здесь остались бы прежние значения (`expire_on_commit`
    # выключен) и `{{node.plan_text}}`/`{{node.user_input}}` пришли бы пустыми.
    stmt = _history_stmt(task.id).execution_options(populate_existing=True)
    entries = list((await db_session.execute(stmt)).scalars().all())
    return NodeContextHistory(
        pipeline_runs=[entry for entry in entries if _is_current_pipeline_run(entry, task)],
        session_replies=[
            entry.llm_output_text
            for entry in entries
            if entry.llm_output_text and _started_since(entry, task.context_cleared_at)
        ],
    )


async def filter_node_logs(
    db_session: AsyncSession,
    task_id: uuid.UUID,
    *,
    node_id: uuid.UUID | None = None,
    status: NodeLogStatus | None = None,
    trigger_type: NodeLogTriggerType | None = None,
) -> list[NodeLog]:
    """
    Записи ``node_logs`` задачи по фильтрам ноды, статуса и источника (``None`` — любой).
    """
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
