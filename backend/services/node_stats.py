"""
Статистика выполнения нод за период (раздел 15.5 ТЗ, «Мониторинг»): итоги
запусков, повторы, длительность и ноды, падающие чаще других. Считается
поверх `node_logs`, как и сводка запусков (раздел 13.4).

Длительность — только у запусков без ожидания пользователя (решения по плану,
ответа на вопрос, разрешения): иначе среднее показывало бы время реакции
человека, а не работу ноды.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING

import sqlalchemy as sa

from db.models.enums import NodeLogStatus
from db.models.logs import NodeLog
from db.models.pipelines import Node

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

TOP_FAILING_LIMIT = 5


class StatsPeriod(StrEnum):
    DAY = "day"
    WEEK = "week"


PERIOD_LENGTH = {StatsPeriod.DAY: timedelta(days=1), StatsPeriod.WEEK: timedelta(days=7)}


@dataclass(frozen=True, slots=True)
class FailingNode:
    node_id: uuid.UUID
    node_name: str
    failed: int


@dataclass(frozen=True, slots=True)
class NodeStats:
    period: StatsPeriod
    since: datetime
    total: int
    success: int
    failed: int
    stopped: int
    retries: int
    avg_duration_seconds: float | None
    max_duration_seconds: float | None
    top_failing: list[FailingNode]


def _count_with(condition: sa.ColumnElement[bool]) -> sa.ColumnElement[int]:
    return sa.func.count().filter(condition)


async def _top_failing(db_session: AsyncSession, *, since: datetime) -> list[FailingNode]:
    failed = sa.func.count().label("failed")
    rows = await db_session.execute(
        sa.select(Node.id, Node.name, failed)
        .join(NodeLog, NodeLog.node_id == Node.id)
        .where(NodeLog.started_at >= since, NodeLog.status == NodeLogStatus.FAILED)
        .group_by(Node.id, Node.name)
        .order_by(failed.desc(), Node.name)
        .limit(TOP_FAILING_LIMIT),
    )
    return [FailingNode(node_id=row.id, node_name=row.name, failed=row.failed) for row in rows]


async def node_stats(
    db_session: AsyncSession,
    *,
    period: StatsPeriod,
    now: datetime,
) -> NodeStats:
    since = now - PERIOD_LENGTH[period]
    duration = sa.func.extract("epoch", NodeLog.finished_at - NodeLog.started_at)
    without_waiting = sa.and_(
        NodeLog.finished_at.is_not(None),
        NodeLog.user_input_text.is_(None),
        NodeLog.pending_question.is_(None),
        NodeLog.pending_plan_text.is_(None),
    )
    row = (
        await db_session.execute(
            sa.select(
                sa.func.count(),
                _count_with(NodeLog.status == NodeLogStatus.SUCCESS),
                _count_with(NodeLog.status == NodeLogStatus.FAILED),
                _count_with(NodeLog.status == NodeLogStatus.STOPPED),
                _count_with(NodeLog.attempt_number > 1),
                sa.func.avg(duration).filter(without_waiting),
                sa.func.max(duration).filter(without_waiting),
            ).where(NodeLog.started_at >= since),
        )
    ).one()
    total, success, failed, stopped, retries, avg_duration, max_duration = row
    return NodeStats(
        period=period,
        since=since,
        total=total,
        success=success,
        failed=failed,
        stopped=stopped,
        retries=retries,
        avg_duration_seconds=float(avg_duration) if avg_duration is not None else None,
        max_duration_seconds=float(max_duration) if max_duration is not None else None,
        top_failing=await _top_failing(db_session, since=since),
    )
