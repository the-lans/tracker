"""Состав включённых нод конкретной задачи (раздел 13.1, 13.2 ТЗ).

`task_nodes` — снимок нод пайплайна на момент привязки; отключение ноды
здесь не меняет сам пайплайн-шаблон и не создаёт записи в `node_logs`
(раздел 22).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

import sqlalchemy as sa

from app_logging.config import get_logger
from db.models.enums import NodeType, TaskStatus
from db.models.pipelines import Node, TaskNode
from db.models.tasks import Task
from services.access import get_task_record_or_404
from services.errors import ConflictError, ValidationError
from services.task_status import lock_task

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger("task_nodes")


@dataclass(frozen=True, slots=True)
class TaskNodeView:
    id: uuid.UUID
    node_id: uuid.UUID
    order_index: int
    is_enabled: bool
    name: str
    node_type: NodeType
    editable: bool


def is_task_node_editable(task: Task, task_node: TaskNode) -> bool:
    """Правило 11 CLAUDE.md: в `new` — любая нода; в `failed` — только ещё
    не начинавшие выполнение (`order_index > last_failed_order_index`);
    после запуска в остальных статусах — никакая."""
    if task.status is TaskStatus.NEW:
        return True
    if task.status is TaskStatus.FAILED and task.last_failed_order_index is not None:
        return task_node.order_index > task.last_failed_order_index
    return False


async def load_task_node_rows(
    db_session: AsyncSession,
    task_id: uuid.UUID,
) -> list[tuple[TaskNode, Node]]:
    """
    Снимок нод задачи (`task_nodes`) вместе с нодами, в порядке выполнения.
    """
    stmt = (
        sa.select(TaskNode, Node)
        .join(Node, Node.id == TaskNode.node_id)
        .where(TaskNode.task_id == task_id)
        .order_by(TaskNode.order_index)
    )
    return [(task_node, node) for task_node, node in (await db_session.execute(stmt)).all()]


async def list_task_nodes(db_session: AsyncSession, task: Task) -> list[TaskNodeView]:
    return [
        TaskNodeView(
            id=task_node.id,
            node_id=node.id,
            order_index=task_node.order_index,
            is_enabled=task_node.is_enabled,
            name=node.name,
            node_type=node.node_type,
            editable=is_task_node_editable(task, task_node),
        )
        for task_node, node in await load_task_node_rows(db_session, task.id)
    ]


async def set_task_node_enabled(
    db_session: AsyncSession,
    *,
    task: Task,
    task_node_id: uuid.UUID,
    is_enabled: bool,
) -> TaskNode:
    task_node = await get_task_record_or_404(
        db_session,
        TaskNode,
        task_node_id,
        task_id=task.id,
        not_found=f"Нода {task_node_id} не найдена у этой задачи",
    )
    if not is_task_node_editable(task, task_node):
        if task.status is TaskStatus.FAILED:
            message = "Нода уже выполнялась в этом прогоне — менять её нельзя (раздел 13.2)"
        else:
            message = "Состав нод можно менять только до запуска или после сбоя (раздел 13.2)"
        raise ConflictError(message)
    task_node.is_enabled = is_enabled
    await db_session.commit()
    logger.info(
        "task_node_toggled",
        task_id=str(task.id),
        task_node_id=str(task_node_id),
        is_enabled=is_enabled,
    )
    return task_node


async def bind_pipeline_to_task(
    db_session: AsyncSession,
    *,
    task: Task,
    pipeline_id: uuid.UUID,
    disabled_node_ids: set[uuid.UUID] | None,
) -> None:
    """
    Раздел 3.1, 13.1, правило 10 CLAUDE.md: снимок нод и `tasks.pipeline_id`
    — одной транзакцией.

    Пока задача в `new`, пайплайн можно сменить: прежний снимок заменяется
    новым в той же транзакции. Строка задачи блокируется до коммита, поэтому
    две одновременные привязки не складывают снимки (решение №19 плана).

    ``disabled_node_ids`` — чекбоксы, снятые пользователем при выборе
    пайплайна; `None` — выбор не делался, и выключены ноды с `is_skipped`
    (раздел 15.4, «пропуск по умолчанию»).
    """
    locked = await lock_task(db_session, task.id)
    if locked is None or locked.status is not TaskStatus.NEW:
        raise ValidationError(
            "Пайплайн можно выбрать или сменить только у задачи в статусе new — "
            "запущенную задачу сначала верните в новые",
        )
    nodes_stmt = sa.select(Node).where(Node.pipeline_id == pipeline_id).order_by(Node.order_index)
    nodes = list((await db_session.execute(nodes_stmt)).scalars().all())
    if not nodes:
        raise ValidationError("У пайплайна нет нод либо он не существует")
    if disabled_node_ids is None:
        disabled_node_ids = {node.id for node in nodes if node.is_skipped}
    unknown = disabled_node_ids - {node.id for node in nodes}
    if unknown:
        raise ValidationError("Отключаемые ноды не принадлежат выбранному пайплайну")

    await db_session.execute(sa.delete(TaskNode).where(TaskNode.task_id == task.id))
    task.pipeline_id = pipeline_id
    for node in nodes:
        db_session.add(
            TaskNode(
                task_id=task.id,
                node_id=node.id,
                order_index=node.order_index or 0,
                is_enabled=node.id not in disabled_node_ids,
            ),
        )
    await db_session.commit()
    logger.info(
        "pipeline_bound_to_task",
        task_id=str(task.id),
        pipeline_id=str(pipeline_id),
        disabled_count=len(disabled_node_ids),
    )
