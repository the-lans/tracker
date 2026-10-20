"""Административный мониторинг (раздел 13.4, 15.5 ТЗ).

- Сводка выполнения нод по всем задачам — отчётная выборка поверх
  `node_logs`, без дублирующей таблицы (раздел 13.4).
- Активные Celery-задачи по всем пользователям (раздел 15.5): список
  берётся у самих воркеров через брокер (`celery inspect active`) — так
  видны все реплики воркера, и не нужно вести свою таблицу запусков.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import sqlalchemy as sa

from db.models.enums import NodeLogStatus, NodeLogTriggerType
from db.models.logs import NodeLog
from db.models.pipelines import Node
from db.models.tasks import Task

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

# Celery-задача, владеющая сессией: первый аргумент — id задачи трекера.
_SESSION_TASK_NAME = "run_task_session"

# Ответ `celery inspect active`: имя воркера -> его выполняющиеся задачи.
InspectActiveResponse = dict[str, list[dict[str, Any]]]


@dataclass(frozen=True, slots=True)
class NodeRunFilters:
    task_id: uuid.UUID | None = None
    node_id: uuid.UUID | None = None
    status: NodeLogStatus | None = None
    trigger_type: NodeLogTriggerType | None = None
    started_from: datetime | None = None
    started_to: datetime | None = None


@dataclass(frozen=True, slots=True)
class NodeRunRow:
    node_log_id: uuid.UUID
    task_id: uuid.UUID
    task_code: str
    node_id: uuid.UUID | None
    node_name: str | None
    trigger_type: NodeLogTriggerType
    attempt_number: int
    status: NodeLogStatus
    started_at: datetime | None
    finished_at: datetime | None


async def list_node_runs(
    db_session: AsyncSession,
    *,
    filters: NodeRunFilters,
    limit: int,
) -> list[NodeRunRow]:
    """Раздел 13.4: какая нода, в какой задаче, когда и с каким итоговым статусом."""
    stmt = (
        sa.select(NodeLog, Task.code, Node.name)
        .join(Task, Task.id == NodeLog.task_id)
        .outerjoin(Node, Node.id == NodeLog.node_id)
        .order_by(NodeLog.started_at.desc().nulls_last(), NodeLog.id)
        .limit(limit)
    )
    conditions = {
        NodeLog.task_id: filters.task_id,
        NodeLog.node_id: filters.node_id,
        NodeLog.status: filters.status,
        NodeLog.trigger_type: filters.trigger_type,
    }
    for column, value in conditions.items():
        if value is not None:
            stmt = stmt.where(column == value)
    if filters.started_from is not None:
        stmt = stmt.where(NodeLog.started_at >= filters.started_from)
    if filters.started_to is not None:
        stmt = stmt.where(NodeLog.started_at <= filters.started_to)
    return [
        NodeRunRow(
            node_log_id=node_log.id,
            task_id=node_log.task_id,
            task_code=task_code,
            node_id=node_log.node_id,
            node_name=node_name,
            trigger_type=node_log.trigger_type,
            attempt_number=node_log.attempt_number,
            status=node_log.status,
            started_at=node_log.started_at,
            finished_at=node_log.finished_at,
        )
        for node_log, task_code, node_name in (await db_session.execute(stmt)).all()
    ]


@dataclass(frozen=True, slots=True)
class ActiveCeleryTask:
    worker: str
    celery_task_id: str
    name: str
    started_at: datetime | None
    task_id: uuid.UUID | None = None
    task_code: str | None = None


def _tracker_task_id(name: str, args: object) -> uuid.UUID | None:
    if name != _SESSION_TASK_NAME or not isinstance(args, list | tuple) or not args:
        return None
    try:
        return uuid.UUID(str(args[0]))
    except ValueError:
        return None


def _started_at(raw: object) -> datetime | None:
    if isinstance(raw, int | float):
        return datetime.fromtimestamp(raw, tz=UTC)
    return None


def parse_active_celery_tasks(raw: InspectActiveResponse | None) -> list[ActiveCeleryTask]:
    """Ответ `inspect().active()` — ``{воркер: [задача, ...]}``; `None` — ни
    один воркер не ответил за отведённое время."""
    tasks: list[ActiveCeleryTask] = []
    for worker, entries in sorted((raw or {}).items()):
        for entry in entries:
            name = str(entry.get("name", ""))
            tasks.append(
                ActiveCeleryTask(
                    worker=worker,
                    celery_task_id=str(entry.get("id", "")),
                    name=name,
                    started_at=_started_at(entry.get("time_start")),
                    task_id=_tracker_task_id(name, entry.get("args")),
                ),
            )
    return tasks


async def attach_task_codes(
    db_session: AsyncSession,
    tasks: list[ActiveCeleryTask],
) -> list[ActiveCeleryTask]:
    """Код задачи трекера для сессионных Celery-задач — чтобы админ видел, чья это сессия."""
    task_ids = {task.task_id for task in tasks if task.task_id is not None}
    if not task_ids:
        return tasks
    rows = await db_session.execute(sa.select(Task.id, Task.code).where(Task.id.in_(task_ids)))
    codes = {task_id: code for task_id, code in rows}
    return [
        ActiveCeleryTask(
            worker=task.worker,
            celery_task_id=task.celery_task_id,
            name=task.name,
            started_at=task.started_at,
            task_id=task.task_id,
            task_code=codes.get(task.task_id) if task.task_id is not None else None,
        )
        for task in tasks
    ]
