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

from db.models.enums import NodeLogStatus, NodeLogTriggerType, NodeType, PlanDecisionOption
from db.models.logs import NodeLog
from db.models.pipelines import Node
from db.models.tasks import Task

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True, slots=True)
class NodeContextHistory:
    """
    Источники ``{{node.*}}`` (раздел 5) в хронологическом порядке.

    ``pipeline_runs`` — успешные выполнения нод пайплайна текущего прогона:
    ни неудачная попытка, ни промт библиотеки, ни свободный промт не
    подменяют вывод предыдущей ноды. ``session_replies`` — ответы LLM
    текущей сессии, после последней очистки контекста.
    ``accepted_plan_text`` — принятый план текущего этапа, включая ручное принятие.
    """

    pipeline_runs: list[NodeLog]
    session_replies: list[str]
    accepted_plan_text: str = ""


EMPTY_NODE_CONTEXT_HISTORY = NodeContextHistory(pipeline_runs=[], session_replies=[])


def _started_since(entry: NodeLog, moment: datetime | None) -> bool:
    return moment is None or (entry.started_at is not None and entry.started_at >= moment)


def _is_current_pipeline_run(entry: NodeLog, task: Task) -> bool:
    # Без ноды — обращение воркера к агенту за разрешением конфликта ребейза
    # (`services/rebase_resolution.py`): это не нода пайплайна.
    return (
        entry.node_id is not None
        and entry.trigger_type is NodeLogTriggerType.PIPELINE
        and entry.status is NodeLogStatus.SUCCESS
        and _started_since(entry, task.reset_at)
    )


async def accepted_plan_text(db_session: AsyncSession, task_id: uuid.UUID) -> str | None:
    """Принятый план этапа после последнего сброса задачи.

    Новая попытка ноды планирования закрывает предыдущий этап, даже если
    попытка остановлена или завершилась ошибкой. Ручное принятие тоже
    сохраняется в истории, поэтому доступно после возобновления сессии.
    """
    reset_at = sa.select(Task.reset_at).where(Task.id == task_id).scalar_subquery()
    explicit_plan = sa.and_(
        NodeLog.trigger_type == NodeLogTriggerType.PIPELINE,
        Node.node_type == NodeType.PLAN_PROMPT,
    )
    saved_plan = NodeLog.plan_execution["plan"].astext
    accepted = sa.or_(
        sa.func.btrim(saved_plan) != "",
        sa.and_(
            NodeLog.status == NodeLogStatus.SUCCESS,
            sa.func.btrim(NodeLog.pending_plan_text) != "",
            sa.func.split_part(NodeLog.user_input_text, "\n", 1).in_(
                (PlanDecisionOption.ACCEPT_AUTO, PlanDecisionOption.ACCEPT_DEFAULT)
            ),
            sa.or_(
                NodeLog.trigger_type.in_(
                    (NodeLogTriggerType.FREEFORM_MANUAL, NodeLogTriggerType.LIBRARY_MANUAL)
                ),
                sa.and_(
                    NodeLog.trigger_type == NodeLogTriggerType.PIPELINE,
                    NodeLog.node_id.is_not(None),
                ),
            ),
        ),
    )
    return await db_session.scalar(
        sa.select(sa.case((accepted, sa.func.coalesce(saved_plan, NodeLog.pending_plan_text))))
        .select_from(NodeLog)
        .outerjoin(Node, Node.id == NodeLog.node_id)
        .where(
            NodeLog.task_id == task_id,
            sa.or_(reset_at.is_(None), NodeLog.started_at >= reset_at),
            sa.or_(explicit_plan, accepted),
        )
        .order_by(NodeLog.started_at.desc().nulls_last(), NodeLog.id.desc())
        .limit(1)
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
        accepted_plan_text=await accepted_plan_text(db_session, task.id) or "",
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
