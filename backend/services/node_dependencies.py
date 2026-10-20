"""
Зависимые ноды при отключении (раздел 13.3, 15.2 ТЗ).

Интерфейс обязан предупредить, если на вывод отключаемой ноды ссылается
последующая активная нода. «Ссылается» здесь значит то же, что при
рендеринге (`services/template_context.py::build_node_context`):
`{{node.X}}` берёт значение у ближайшей предшествующей включённой ноды,
которая его производит. Отключение такой ноды подменяет источник — или
оставляет переменную пустой.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

import sqlalchemy as sa

from db.models.enums import NodeType
from db.models.pipelines import Node, TaskNode
from services.errors import NotFoundError
from services.templating import NODE_FIELD_REQUIRED_PRECEDING_TYPES, VARIABLE_PATTERN

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from db.models.tasks import Task

_NODE_NAMESPACE = "node"
_LLM_OUTPUT_LAST_N = "llm_output_last_n"
# Ноды, чей ответ попадает в `{{node.llm_output_last_n}}` (`llm_output_text`).
_LLM_OUTPUT_PRODUCERS = frozenset(
    {NodeType.PLAIN_PROMPT, NodeType.SLASH_COMMAND, NodeType.PLAN_PROMPT},
)


@dataclass(frozen=True, slots=True)
class PipelineNodeRef:
    node_id: uuid.UUID
    name: str
    order_index: int
    node_type: NodeType
    prompt_template: str | None
    llm_output_last_n: int | None
    is_enabled: bool


def _referenced_node_fields(node: PipelineNodeRef) -> set[str]:
    if node.prompt_template is None:
        return set()
    return {
        field
        for namespace, field in VARIABLE_PATTERN.findall(node.prompt_template)
        if namespace == _NODE_NAMESPACE
    }


def _sources_of(
    field: str,
    *,
    preceding: Sequence[PipelineNodeRef],
    last_n: int | None,
) -> list[PipelineNodeRef]:
    """
    Ноды, чей вывод подставится в ``{{node.<field>}}``; ``preceding`` —
    включённые ноды до текущей, в порядке выполнения.
    """
    if field == _LLM_OUTPUT_LAST_N:
        producers = [node for node in preceding if node.node_type in _LLM_OUTPUT_PRODUCERS]
        return producers[-last_n:] if last_n else []
    required_types = NODE_FIELD_REQUIRED_PRECEDING_TYPES.get(field, frozenset())
    for node in reversed(preceding):
        if node.node_type in required_types:
            return [node]
    return []


def find_dependent_nodes(
    nodes: Sequence[PipelineNodeRef],
    target_node_id: uuid.UUID,
) -> list[PipelineNodeRef]:
    """
    Последующие включённые ноды, которые берут вывод у ``target_node_id``.

    Источник ищется так, будто отключаемая нода ещё включена: важна именно
    она, а не то, что переменная получит после отключения.
    """
    ordered = sorted(nodes, key=lambda node: node.order_index)
    active = [node for node in ordered if node.is_enabled or node.node_id == target_node_id]
    target_position = next(
        (index for index, node in enumerate(active) if node.node_id == target_node_id),
        None,
    )
    if target_position is None:
        return []
    dependents: list[PipelineNodeRef] = []
    for position in range(target_position + 1, len(active)):
        node = active[position]
        preceding = active[:position]
        for field in _referenced_node_fields(node):
            sources = _sources_of(field, preceding=preceding, last_n=node.llm_output_last_n)
            if any(source.node_id == target_node_id for source in sources):
                dependents.append(node)
                break
    return dependents


def _node_ref(node: Node, *, is_enabled: bool, order_index: int) -> PipelineNodeRef:
    return PipelineNodeRef(
        node_id=node.id,
        name=node.name,
        order_index=order_index,
        node_type=node.node_type,
        prompt_template=node.prompt_template,
        llm_output_last_n=node.llm_output_last_n,
        is_enabled=is_enabled,
    )


async def find_task_node_dependents(
    db_session: AsyncSession,
    *,
    task: Task,
    task_node_id: uuid.UUID,
) -> list[PipelineNodeRef]:
    """Зависимые ноды по текущему составу `task_nodes` задачи."""
    stmt = (
        sa.select(TaskNode, Node)
        .join(Node, Node.id == TaskNode.node_id)
        .where(TaskNode.task_id == task.id)
    )
    rows = (await db_session.execute(stmt)).all()
    target = next((task_node for task_node, _ in rows if task_node.id == task_node_id), None)
    if target is None:
        raise NotFoundError(f"Нода {task_node_id} не найдена у этой задачи")
    refs = [
        _node_ref(node, is_enabled=task_node.is_enabled, order_index=task_node.order_index)
        for task_node, node in rows
    ]
    return find_dependent_nodes(refs, target.node_id)


async def find_pipeline_node_dependents(
    db_session: AsyncSession,
    *,
    pipeline_id: uuid.UUID,
    node_id: uuid.UUID,
    enabled_node_ids: set[uuid.UUID],
) -> list[PipelineNodeRef]:
    """Зависимые ноды при выборе пайплайна, пока `task_nodes` ещё не созданы."""
    stmt = sa.select(Node).where(Node.pipeline_id == pipeline_id)
    nodes = list((await db_session.execute(stmt)).scalars().all())
    if all(node.id != node_id for node in nodes):
        raise NotFoundError(f"Нода {node_id} не найдена в пайплайне")
    refs = [
        _node_ref(node, is_enabled=node.id in enabled_node_ids, order_index=node.order_index or 0)
        for node in nodes
    ]
    return find_dependent_nodes(refs, node_id)
