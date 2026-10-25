"""
Проверка ноды и пайплайна при сохранении (раздел 3.1, 5.1, 7.2, 9.5, 15.4 ТЗ).

Раздел 5.1: недоступная переменная шаблона — ошибка СОХРАНЕНИЯ, а не сбой
при выполнении. Доступность `{{node.*}}` зависит от предыдущих нод, поэтому
после любого изменения состава пайплайна (создание, изменение, удаление,
перестановка ноды) проверяются все его ноды, а не только изменённая.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import sqlalchemy as sa

from db.models.enums import NodeType
from db.models.pipelines import Node, TaskNode
from services.errors import ValidationError
from services.templating import RenderScope, validate_template_variables

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.ext.asyncio import AsyncSession

# Раздел 7.2: типы, бессмысленные для библиотеки (разовые пайплайн-действия).
_LIBRARY_FORBIDDEN_NODE_TYPES = frozenset({NodeType.CLEAR_CONTEXT, NodeType.PLAN_PROMPT})
# Раздел 13.1: своя нода задачи — промт или слэш-команда.
CUSTOM_TASK_NODE_TYPES = frozenset({NodeType.PLAIN_PROMPT, NodeType.SLASH_COMMAND})

# Нода и её позиция в порядке выполнения (`None` — позиции нет).
type OrderedNodes = list[tuple[int | None, Node]]


def validate_node_shape(node: Node, *, check_description: bool = True) -> None:
    """
    Ограничения одной ноды, не зависящие от соседей по пайплайну.

    ``check_description`` — проверять ли обязательное описание промта
    библиотеки: при создании и при изменении описания. Прочие правки (в том
    числе архивация) промтов, заведённых до этого правила, не блокируются.
    """
    if node.task_id is not None:
        if node.node_type not in CUSTOM_TASK_NODE_TYPES:
            raise ValidationError(
                "Свой промт задачи — только промт или слэш-команда (раздел 13.1 ТЗ)",
            )
        return
    if node.node_type is NodeType.PLAN_PROMPT and node.pipeline_id is None:
        raise ValidationError("plan_prompt допустим только внутри пайплайна (раздел 9.5 ТЗ)")
    if node.pipeline_id is not None:
        return
    if node.node_type in _LIBRARY_FORBIDDEN_NODE_TYPES:
        raise ValidationError(
            f"Тип ноды {node.node_type} недопустим для библиотеки промтов (раздел 7.2 ТЗ)",
        )
    if check_description and not (node.description or "").strip():
        raise ValidationError("Описание обязательно для промта библиотеки (раздел 3.1 ТЗ)")
    if node.prompt_template is not None:
        validate_template_variables(node.prompt_template, scope=RenderScope.LIBRARY)


async def _pipeline_nodes(db_session: AsyncSession, pipeline_id: uuid.UUID) -> OrderedNodes:
    stmt = (
        sa.select(Node)
        .where(Node.pipeline_id == pipeline_id)
        .order_by(Node.order_index, Node.id)
    )
    return [(node.order_index, node) for node in (await db_session.execute(stmt)).scalars().all()]


async def task_composition(db_session: AsyncSession, task_id: uuid.UUID) -> OrderedNodes:
    """Состав задачи: ноды снимка `task_nodes`, включая свои, в его порядке (раздел 13.1)."""
    stmt = (
        sa.select(TaskNode.order_index, Node)
        .join(Node, Node.id == TaskNode.node_id)
        .where(TaskNode.task_id == task_id)
        .order_by(TaskNode.order_index)
    )
    return [(order_index, node) for order_index, node in (await db_session.execute(stmt)).all()]


def _preceding_node_types(
    nodes: OrderedNodes,
    *,
    order_index: int | None,
    exclude_node_id: uuid.UUID | None = None,
) -> list[NodeType]:
    """Типы нод, стоящих строго раньше позиции ``order_index``."""
    if order_index is None:
        return []
    return [
        other.node_type
        for position, other in nodes
        if position is not None and position < order_index and other.id != exclude_node_id
    ]


@dataclass(frozen=True, slots=True)
class PipelinePosition:
    """
    Контекст ``{{node.*}}`` для ноды на позиции пайплайна — тот же, что при
    сохранении (раздел 5.1): предпросмотр не должен отклонять шаблон,
    который сохранение примет.
    """

    preceding_node_types: list[NodeType] = field(default_factory=list)
    llm_output_last_n: int | None = None


async def pipeline_position(
    db_session: AsyncSession,
    *,
    pipeline_id: uuid.UUID,
    order_index: int | None,
    node: Node | None = None,
) -> PipelinePosition:
    """Позиция ``order_index`` пайплайна; ``node`` — редактируемая нода, если она уже сохранена."""
    return _position_in(
        await _pipeline_nodes(db_session, pipeline_id),
        order_index=order_index,
        node=node,
    )


async def task_position(
    db_session: AsyncSession,
    *,
    task_id: uuid.UUID,
    order_index: int | None,
    node: Node | None = None,
) -> PipelinePosition:
    """Позиция ``order_index`` в составе задачи — для предпросмотра своей ноды (раздел 13.1)."""
    nodes = await task_composition(db_session, task_id)
    return _position_in(nodes, order_index=order_index, node=node)


def _position_in(
    nodes: OrderedNodes,
    *,
    order_index: int | None,
    node: Node | None,
) -> PipelinePosition:
    return PipelinePosition(
        preceding_node_types=_preceding_node_types(
            nodes,
            order_index=order_index,
            exclude_node_id=node.id if node is not None else None,
        ),
        llm_output_last_n=node.llm_output_last_n if node is not None else None,
    )


async def validate_pipeline_templates(db_session: AsyncSession, pipeline_id: uuid.UUID) -> None:
    """
    Все ноды пайплайна в текущем (ещё не закоммиченном) порядке: каждой
    ``{{node.*}}`` должен предшествовать источник подходящего типа.
    """
    _validate_ordered_templates(await _pipeline_nodes(db_session, pipeline_id))


def validate_custom_node_templates(nodes: OrderedNodes) -> None:
    """
    Свои ноды задачи по её составу (раздел 13.1) — до записи изменения:
    перепроверяются все свои ноды. Ноды пайплайна уже проверены при
    сохранении пайплайна, а свои ноды только добавляют им источников
    `{{node.*}}`.
    """
    _validate_ordered_templates(nodes, only=lambda node: node.task_id is not None)


def _validate_ordered_templates(
    nodes: OrderedNodes,
    *,
    only: Callable[[Node], bool] | None = None,
) -> None:
    for order_index, node in nodes:
        if node.prompt_template is None or (only is not None and not only(node)):
            continue
        preceding_types = _preceding_node_types(nodes, order_index=order_index)
        try:
            validate_template_variables(
                node.prompt_template,
                scope=RenderScope.PIPELINE,
                preceding_node_types=preceding_types,
                current_node_llm_output_last_n=node.llm_output_last_n,
            )
        except ValidationError as exc:
            raise ValidationError(f"Нода «{node.name}»: {exc.message}") from exc
