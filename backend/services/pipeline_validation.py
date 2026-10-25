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
from db.models.pipelines import Node
from services.errors import ValidationError
from services.templating import RenderScope, validate_template_variables

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

# Раздел 7.2: типы, бессмысленные для библиотеки (разовые пайплайн-действия).
_LIBRARY_FORBIDDEN_NODE_TYPES = frozenset({NodeType.CLEAR_CONTEXT, NodeType.PLAN_PROMPT})


def validate_node_shape(node: Node, *, check_description: bool = True) -> None:
    """
    Ограничения одной ноды, не зависящие от соседей по пайплайну.

    ``check_description`` — проверять ли обязательное описание промта
    библиотеки: при создании и при изменении описания. Прочие правки (в том
    числе архивация) промтов, заведённых до этого правила, не блокируются.
    """
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


async def _pipeline_nodes(db_session: AsyncSession, pipeline_id: uuid.UUID) -> list[Node]:
    stmt = (
        sa.select(Node)
        .where(Node.pipeline_id == pipeline_id)
        .order_by(Node.order_index, Node.id)
    )
    return list((await db_session.execute(stmt)).scalars().all())


def _preceding_node_types(
    nodes: list[Node],
    *,
    order_index: int | None,
    exclude_node_id: uuid.UUID | None = None,
) -> list[NodeType]:
    """Типы нод, стоящих строго раньше позиции ``order_index``."""
    if order_index is None:
        return []
    return [
        other.node_type
        for other in nodes
        if other.order_index is not None
        and other.order_index < order_index
        and other.id != exclude_node_id
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
    nodes = await _pipeline_nodes(db_session, pipeline_id)
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
    nodes = await _pipeline_nodes(db_session, pipeline_id)
    for node in nodes:
        if node.prompt_template is None:
            continue
        preceding_types = _preceding_node_types(nodes, order_index=node.order_index)
        try:
            validate_template_variables(
                node.prompt_template,
                scope=RenderScope.PIPELINE,
                preceding_node_types=preceding_types,
                current_node_llm_output_last_n=node.llm_output_last_n,
            )
        except ValidationError as exc:
            raise ValidationError(f"Нода «{node.name}»: {exc.message}") from exc
