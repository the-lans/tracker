"""CRUD `nodes` (раздел 3.1, 3.2, 5.1, 7.2 ТЗ) — нода пайплайна и промт
библиотеки одной сущностью (см. `db/models/pipelines.py::Node`).

Раздел 5.1: недоступная переменная шаблона — ошибка валидации СОХРАНЕНИЯ,
а не рантайм-сбой, поэтому `prompt_template` прогоняется через
`services.templating.validate_template_variables` здесь же, при
создании/редактировании ноды.
"""

from __future__ import annotations

import uuid
from typing import Annotated

import sqlalchemy as sa
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_current_user
from api.schemas import NodeCreateRequest, NodeResponse, NodeUpdateRequest
from db.models.enums import NodeType
from db.models.pipelines import Node
from db.models.users import User
from db.session import get_session
from services.errors import NotFoundError, ValidationError
from services.integrity import ensure_node_deletable
from services.templating import RenderScope, validate_template_variables

router = APIRouter(prefix="/nodes", tags=["nodes"])

# Раздел 7.2: типы, бессмысленные для библиотеки (разовые пайплайн-действия).
_LIBRARY_FORBIDDEN_NODE_TYPES = frozenset({NodeType.CLEAR_CONTEXT, NodeType.PLAN_PROMPT})


async def _get_node_or_404(db_session: AsyncSession, node_id: uuid.UUID) -> Node:
    node = await db_session.get(Node, node_id)
    if node is None:
        raise NotFoundError(f"Нода/промт {node_id} не найден")
    return node


async def _preceding_node_types(
    db_session: AsyncSession,
    *,
    pipeline_id: uuid.UUID,
    order_index: int | None,
) -> list[NodeType]:
    if order_index is None:
        return []
    stmt = sa.select(Node.node_type).where(
        Node.pipeline_id == pipeline_id,
        Node.order_index < order_index,
    )
    return list((await db_session.execute(stmt)).scalars().all())


async def _validate_node_prompt(
    db_session: AsyncSession,
    *,
    pipeline_id: uuid.UUID | None,
    order_index: int | None,
    node_type: NodeType,
    prompt_template: str | None,
    llm_output_last_n: int | None,
) -> None:
    if node_type is NodeType.PLAN_PROMPT and pipeline_id is None:
        raise ValidationError("plan_prompt допустим только внутри пайплайна (раздел 9.5 ТЗ)")
    if pipeline_id is None and node_type in _LIBRARY_FORBIDDEN_NODE_TYPES:
        raise ValidationError(
            f"Тип ноды {node_type} недопустим для библиотеки промтов (раздел 7.2 ТЗ)",
        )
    if prompt_template is None:
        return
    if pipeline_id is not None:
        preceding_types = await _preceding_node_types(
            db_session,
            pipeline_id=pipeline_id,
            order_index=order_index,
        )
        validate_template_variables(
            prompt_template,
            scope=RenderScope.PIPELINE,
            preceding_node_types=preceding_types,
            current_node_llm_output_last_n=llm_output_last_n,
        )
    else:
        validate_template_variables(prompt_template, scope=RenderScope.LIBRARY)


@router.post("", response_model=NodeResponse, status_code=201)
async def create_node(
    body: NodeCreateRequest,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    _current_user: Annotated[User, Depends(get_current_user)],
) -> Node:
    await _validate_node_prompt(
        db_session,
        pipeline_id=body.pipeline_id,
        order_index=body.order_index,
        node_type=body.node_type,
        prompt_template=body.prompt_template,
        llm_output_last_n=body.llm_output_last_n,
    )
    node = Node(
        id=uuid.uuid4(),
        pipeline_id=body.pipeline_id,
        order_index=body.order_index,
        name=body.name,
        description=body.description,
        node_type=body.node_type,
        prompt_template=body.prompt_template,
        command_invocation=body.command_invocation,
        script_language=body.script_language,
        script_content=body.script_content,
        docker_image=body.docker_image,
        timeout_seconds=body.timeout_seconds,
        max_retries=body.max_retries,
        retry_base_delay_seconds=body.retry_base_delay_seconds,
        guide_url=body.guide_url,
        is_skipped=body.is_skipped,
        is_library_item=body.pipeline_id is None,
        llm_output_last_n=body.llm_output_last_n,
    )
    db_session.add(node)
    await db_session.commit()
    return node


@router.get("", response_model=list[NodeResponse])
async def list_nodes(
    db_session: Annotated[AsyncSession, Depends(get_session)],
    _current_user: Annotated[User, Depends(get_current_user)],
    library_only: bool = False,
    include_archived: bool = False,
) -> list[Node]:
    stmt = sa.select(Node).order_by(Node.name)
    if library_only:
        stmt = stmt.where(Node.is_library_item == True)  # noqa: E712
    if not include_archived:
        stmt = stmt.where(Node.is_archived == False)  # noqa: E712
    return list((await db_session.execute(stmt)).scalars().all())


@router.get("/{node_id}", response_model=NodeResponse)
async def get_node(
    node_id: uuid.UUID,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    _current_user: Annotated[User, Depends(get_current_user)],
) -> Node:
    return await _get_node_or_404(db_session, node_id)


@router.patch("/{node_id}", response_model=NodeResponse)
async def update_node(
    node_id: uuid.UUID,
    body: NodeUpdateRequest,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    _current_user: Annotated[User, Depends(get_current_user)],
) -> Node:
    node = await _get_node_or_404(db_session, node_id)
    if body.order_index is not None:
        node.order_index = body.order_index
    if body.name is not None:
        node.name = body.name
    if body.description is not None:
        node.description = body.description
    if body.prompt_template is not None:
        node.prompt_template = body.prompt_template
    if body.command_invocation is not None:
        node.command_invocation = body.command_invocation
    if body.script_language is not None:
        node.script_language = body.script_language
    if body.script_content is not None:
        node.script_content = body.script_content
    if body.docker_image is not None:
        node.docker_image = body.docker_image
    if body.timeout_seconds is not None:
        node.timeout_seconds = body.timeout_seconds
    if body.max_retries is not None:
        node.max_retries = body.max_retries
    if body.retry_base_delay_seconds is not None:
        node.retry_base_delay_seconds = body.retry_base_delay_seconds
    if body.guide_url is not None:
        node.guide_url = body.guide_url
    if body.is_skipped is not None:
        node.is_skipped = body.is_skipped
    if body.is_archived is not None:
        node.is_archived = body.is_archived
    if body.llm_output_last_n is not None:
        node.llm_output_last_n = body.llm_output_last_n

    await _validate_node_prompt(
        db_session,
        pipeline_id=node.pipeline_id,
        order_index=node.order_index,
        node_type=node.node_type,
        prompt_template=node.prompt_template,
        llm_output_last_n=node.llm_output_last_n,
    )
    await db_session.commit()
    await db_session.refresh(node)
    return node


@router.delete("/{node_id}", status_code=204)
async def delete_node(
    node_id: uuid.UUID,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    _current_user: Annotated[User, Depends(get_current_user)],
) -> None:
    """Правило 9 CLAUDE.md/раздел 3.2: системный промт, привязанный хотя бы
    к одной задаче, нельзя удалить — только заархивировать."""
    node = await _get_node_or_404(db_session, node_id)
    await ensure_node_deletable(db_session, node_id)
    await db_session.delete(node)
    await db_session.commit()
