"""CRUD `pipelines` (раздел 3.1, 3.2 ТЗ)."""

from __future__ import annotations

import uuid
from typing import Annotated

import sqlalchemy as sa
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_current_user
from api.schemas import (
    NodeDependentResponse,
    NodeResponse,
    PipelineCreateRequest,
    PipelineDependentsRequest,
    PipelineResponse,
    PipelineUpdateRequest,
)
from db.models.pipelines import Node, Pipeline
from db.models.users import User
from db.session import get_session
from services.errors import NotFoundError
from services.integrity import ensure_pipeline_deletable
from services.node_dependencies import find_pipeline_node_dependents

router = APIRouter(prefix="/pipelines", tags=["pipelines"])


async def _get_pipeline_or_404(db_session: AsyncSession, pipeline_id: uuid.UUID) -> Pipeline:
    pipeline = await db_session.get(Pipeline, pipeline_id)
    if pipeline is None:
        raise NotFoundError(f"Пайплайн {pipeline_id} не найден")
    return pipeline


@router.post("", response_model=PipelineResponse, status_code=201)
async def create_pipeline(
    body: PipelineCreateRequest,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    _current_user: Annotated[User, Depends(get_current_user)],
) -> Pipeline:
    pipeline = Pipeline(id=uuid.uuid4(), name=body.name)
    db_session.add(pipeline)
    await db_session.commit()
    return pipeline


@router.get("", response_model=list[PipelineResponse])
async def list_pipelines(
    db_session: Annotated[AsyncSession, Depends(get_session)],
    _current_user: Annotated[User, Depends(get_current_user)],
    include_archived: bool = False,
) -> list[Pipeline]:
    stmt = sa.select(Pipeline).order_by(Pipeline.name)
    if not include_archived:
        stmt = stmt.where(Pipeline.is_archived == False)  # noqa: E712
    return list((await db_session.execute(stmt)).scalars().all())


@router.get("/{pipeline_id}", response_model=PipelineResponse)
async def get_pipeline(
    pipeline_id: uuid.UUID,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    _current_user: Annotated[User, Depends(get_current_user)],
) -> Pipeline:
    return await _get_pipeline_or_404(db_session, pipeline_id)


@router.get("/{pipeline_id}/nodes", response_model=list[NodeResponse])
async def list_pipeline_nodes(
    pipeline_id: uuid.UUID,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    _current_user: Annotated[User, Depends(get_current_user)],
) -> list[Node]:
    await _get_pipeline_or_404(db_session, pipeline_id)
    stmt = sa.select(Node).where(Node.pipeline_id == pipeline_id).order_by(Node.order_index)
    return list((await db_session.execute(stmt)).scalars().all())


@router.patch("/{pipeline_id}", response_model=PipelineResponse)
async def update_pipeline(
    pipeline_id: uuid.UUID,
    body: PipelineUpdateRequest,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    _current_user: Annotated[User, Depends(get_current_user)],
) -> Pipeline:
    pipeline = await _get_pipeline_or_404(db_session, pipeline_id)
    if body.name is not None:
        pipeline.name = body.name
    if body.is_archived is not None:
        pipeline.is_archived = body.is_archived
    await db_session.commit()
    await db_session.refresh(pipeline)
    return pipeline


@router.delete("/{pipeline_id}", status_code=204)
async def delete_pipeline(
    pipeline_id: uuid.UUID,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    _current_user: Annotated[User, Depends(get_current_user)],
) -> None:
    """Правило 9 CLAUDE.md/раздел 3.2: пайплайн, используемый хотя бы одной
    задачей, нельзя удалить — только заархивировать (`PATCH .../is_archived`).

    Guard уже гарантирует отсутствие ссылающихся задач, поэтому ноды
    пайплайна можно удалить вместе с ним — иначе они остались бы
    осиротевшими записями без пайплайна."""
    await _get_pipeline_or_404(db_session, pipeline_id)
    await ensure_pipeline_deletable(db_session, pipeline_id)
    await db_session.execute(sa.delete(Node).where(Node.pipeline_id == pipeline_id))
    await db_session.execute(sa.delete(Pipeline).where(Pipeline.id == pipeline_id))
    await db_session.commit()


@router.post("/{pipeline_id}/dependents", response_model=list[NodeDependentResponse])
async def list_pipeline_node_dependents(
    pipeline_id: uuid.UUID,
    body: PipelineDependentsRequest,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    _current_user: Annotated[User, Depends(get_current_user)],
) -> list[NodeDependentResponse]:
    """
    Раздел 13.3, 15.2: предупреждение при снятии чекбокса в окне выбора
    пайплайна, пока `task_nodes` задачи ещё не созданы.
    """
    dependents = await find_pipeline_node_dependents(
        db_session,
        pipeline_id=pipeline_id,
        node_id=body.node_id,
        enabled_node_ids=set(body.enabled_node_ids),
    )
    return [NodeDependentResponse.model_validate(node) for node in dependents]
