"""
CRUD `nodes` (раздел 3.1, 3.2, 5.1, 7.2 ТЗ) — нода пайплайна и промт
библиотеки одной сущностью (см. `db/models/pipelines.py::Node`).

Раздел 5.1: недоступная переменная шаблона — ошибка валидации СОХРАНЕНИЯ, а
не рантайм-сбой. После каждого изменения состава пайплайна весь пайплайн
перепроверяется до коммита (`services/pipeline_validation.py`): ошибка
откатывает изменение.
"""

from __future__ import annotations

import uuid
from typing import Annotated

import sqlalchemy as sa
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_current_user, require_admin
from api.schemas import (
    LibraryUsageResponse,
    NodeCreateRequest,
    NodeResponse,
    NodeUpdateRequest,
)
from db.models.pipelines import Node
from db.models.users import User
from db.session import get_session
from services.access import get_node_for_user, get_pipeline_for_user, owner_filter
from services.command_arguments import normalize_slash_name
from services.errors import ConflictError, NotFoundError
from services.integrity import (
    count_library_prompt_usage,
    ensure_node_deletable,
    library_item_is_linked,
)
from services.library_commands import validate_command_node
from services.library_links import attach_library_source
from services.pipeline_validation import (
    drop_unused_guide,
    validate_node_shape,
    validate_pipeline_templates,
)

router = APIRouter(prefix="/nodes", tags=["nodes"])


async def _get_node_or_404(db_session: AsyncSession, node_id: uuid.UUID, user: User) -> Node:
    """
    Раздел 19.2: чужая нода/промт для `user` неотличимы от несуществующих.
    Своя нода задачи (раздел 13.1) меняется только со страницы задачи.
    """
    node = await get_node_for_user(db_session, node_id, user=user)
    if node.task_id is not None:
        raise NotFoundError(f"Нода {node_id} не найден(а)")
    return node


async def _node_owner_id(
    db_session: AsyncSession,
    *,
    pipeline_id: uuid.UUID | None,
    user: User,
) -> uuid.UUID:
    """
    Автор новой ноды: у ноды пайплайна — автор пайплайна (доступ к нему
    проверяется здесь же), у промта библиотеки — создающий пользователь.
    """
    if pipeline_id is None:
        return user.id
    pipeline = await get_pipeline_for_user(db_session, pipeline_id, user=user)
    return pipeline.created_by


async def _validate_and_flush(
    db_session: AsyncSession,
    node: Node,
    *,
    check_description: bool = True,
) -> None:
    """Проверка ноды и — для ноды пайплайна — всего пайплайна в новом составе."""
    drop_unused_guide(node)
    validate_node_shape(node, check_description=check_description)
    validate_command_node(node)
    db_session.add(node)
    try:
        await db_session.flush()
    except sa.exc.IntegrityError as exc:
        await db_session.rollback()
        if "uq_nodes_owner_slash_name" in str(exc):
            raise ConflictError("Это имя команды уже занято в вашей библиотеке") from exc
        raise
    if node.pipeline_id is not None:
        await validate_pipeline_templates(db_session, node.pipeline_id)


async def _apply_library_link(
    db_session: AsyncSession,
    node: Node,
    body: NodeUpdateRequest,
) -> None:
    """Раздел 7.6: не переданные поля ссылки остаются прежними."""
    passed = body.model_fields_set
    if not passed.intersection({"library_node_id", "library_arguments", "library_plan_mode"}):
        return
    await attach_library_source(
        db_session,
        node,
        library_node_id=(
            body.library_node_id if "library_node_id" in passed else node.library_node_id
        ),
        plan_mode=body.library_plan_mode,
        arguments=(
            body.library_arguments if "library_arguments" in passed else node.library_arguments
        ),
    )


@router.post("", response_model=NodeResponse, status_code=201)
async def create_node(
    body: NodeCreateRequest,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> Node:
    created_by = await _node_owner_id(db_session, pipeline_id=body.pipeline_id, user=current_user)
    node = Node(
        id=uuid.uuid4(),
        pipeline_id=body.pipeline_id,
        order_index=body.order_index,
        name=body.name,
        slash_name=normalize_slash_name(body.slash_name),
        argument_hint=body.argument_hint,
        description=body.description,
        node_type=body.node_type,
        prompt_template=body.prompt_template,
        command_invocation=body.command_invocation,
        script_language=body.script_language,
        script_content=body.script_content,
        docker_image=body.docker_image,
        guide_url=body.guide_url,
        is_skipped=body.is_skipped,
        pause_after=body.pause_after,
        is_library_item=body.pipeline_id is None,
        llm_output_last_n=body.llm_output_last_n,
        reasoning_effort=body.reasoning_effort,
        created_by=created_by,
    )
    await attach_library_source(
        db_session,
        node,
        library_node_id=body.library_node_id,
        arguments=body.library_arguments,
        plan_mode=body.library_plan_mode,
    )
    await _validate_and_flush(db_session, node)
    await db_session.commit()
    return node


@router.get("", response_model=list[NodeResponse])
async def list_nodes(
    db_session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
    library_only: bool = False,
    include_archived: bool = False,
) -> list[Node]:
    stmt = (
        sa.select(Node)
        .where(owner_filter(Node.created_by, current_user), Node.task_id.is_(None))
        .order_by(Node.name)
    )
    if library_only:
        stmt = stmt.where(Node.is_library_item == True)  # noqa: E712
    if not include_archived:
        stmt = stmt.where(Node.is_archived == False)  # noqa: E712
    return list((await db_session.execute(stmt)).scalars().all())


@router.get("/library-usage", response_model=list[LibraryUsageResponse])
async def list_library_usage(
    db_session: Annotated[AsyncSession, Depends(get_session)],
    _admin: Annotated[User, Depends(require_admin)],
) -> list[LibraryUsageResponse]:
    """Раздел 15.5: в скольких задачах используется каждый промт библиотеки."""
    return [
        LibraryUsageResponse(node_id=node_id, task_count=task_count)
        for node_id, task_count in await count_library_prompt_usage(db_session)
    ]


@router.get("/{node_id}", response_model=NodeResponse)
async def get_node(
    node_id: uuid.UUID,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> Node:
    return await _get_node_or_404(db_session, node_id, current_user)


@router.patch("/{node_id}", response_model=NodeResponse)
async def update_node(
    node_id: uuid.UUID,
    body: NodeUpdateRequest,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> Node:
    node = await _get_node_or_404(db_session, node_id, current_user)
    await db_session.refresh(node, with_for_update=True)
    if (
        node.is_library_item
        and body.node_type is not None
        and body.node_type != node.node_type
        and await library_item_is_linked(db_session, node.id)
    ):
        raise ConflictError("Нельзя изменить тип промта, используемого в пайплайнах")
    node.revision += 1
    if "slash_name" in body.model_fields_set:
        node.slash_name = normalize_slash_name(body.slash_name)
    if "argument_hint" in body.model_fields_set:
        node.argument_hint = body.argument_hint
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
    if "guide_url" in body.model_fields_set:
        node.guide_url = body.guide_url
    if body.is_skipped is not None:
        node.is_skipped = body.is_skipped
    if body.pause_after is not None:
        node.pause_after = body.pause_after
    if body.is_archived is not None:
        node.is_archived = body.is_archived
    if body.llm_output_last_n is not None:
        node.llm_output_last_n = body.llm_output_last_n
    if "reasoning_effort" in body.model_fields_set:
        node.reasoning_effort = body.reasoning_effort
    await _apply_library_link(db_session, node, body)
    if body.node_type is not None and node.library_node_id is None:
        node.node_type = body.node_type

    await _validate_and_flush(
        db_session,
        node,
        check_description=body.description is not None,
    )
    await db_session.commit()
    await db_session.refresh(node)
    return node


@router.delete("/{node_id}", status_code=204)
async def delete_node(
    node_id: uuid.UUID,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> None:
    """Правило 9 CLAUDE.md/раздел 3.2: системный промт, привязанный хотя бы
    к одной задаче, нельзя удалить — только заархивировать."""
    node = await _get_node_or_404(db_session, node_id, current_user)
    await db_session.refresh(node, with_for_update=True)
    await ensure_node_deletable(db_session, node)
    pipeline_id = node.pipeline_id
    await db_session.delete(node)
    await db_session.flush()
    if pipeline_id is not None:
        # Раздел 5.1: удалённая нода могла быть источником `{{node.*}}` следующих.
        await validate_pipeline_templates(db_session, pipeline_id)
    await db_session.commit()
