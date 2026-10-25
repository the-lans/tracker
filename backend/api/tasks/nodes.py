"""
Ноды задачи и история их выполнения (раздел 11, 13.4 ТЗ).
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_current_user
from api.schemas import (
    NodeDependentResponse,
    NodeLogResponse,
    TaskNodeResponse,
    TaskNodeUpdateRequest,
)
from api.tasks.common import TASKS_PREFIX, TASKS_TAGS, get_task_or_404
from db.models.enums import NodeLogStatus, NodeLogTriggerType
from db.models.logs import NodeLog
from db.models.users import User
from db.session import get_session
from services.node_dependencies import find_task_node_dependents
from services.node_history import filter_node_logs
from services.task_nodes import list_task_nodes, set_task_node_enabled

router = APIRouter(prefix=TASKS_PREFIX, tags=TASKS_TAGS)


@router.get("/{task_id}/nodes", response_model=list[TaskNodeResponse])
async def list_nodes_of_task(
    task_id: uuid.UUID,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> list[TaskNodeResponse]:
    task = await get_task_or_404(db_session, task_id, current_user)
    return [
        TaskNodeResponse.model_validate(view) for view in await list_task_nodes(db_session, task)
    ]


@router.patch("/{task_id}/nodes/{task_node_id}", response_model=TaskNodeResponse)
async def update_task_node(
    task_id: uuid.UUID,
    task_node_id: uuid.UUID,
    body: TaskNodeUpdateRequest,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> TaskNodeResponse:
    """Раздел 13.1, 13.2 (правило 11 CLAUDE.md)."""
    task = await get_task_or_404(db_session, task_id, current_user)
    await set_task_node_enabled(
        db_session,
        task=task,
        task_node_id=task_node_id,
        is_enabled=body.is_enabled,
    )
    views = await list_task_nodes(db_session, task)
    return TaskNodeResponse.model_validate(next(v for v in views if v.id == task_node_id))


@router.get(
    "/{task_id}/nodes/{task_node_id}/dependents",
    response_model=list[NodeDependentResponse],
)
async def list_task_node_dependents(
    task_id: uuid.UUID,
    task_node_id: uuid.UUID,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> list[NodeDependentResponse]:
    """Раздел 13.3, 15.2: кого затронет отключение ноды — для предупреждения."""
    task = await get_task_or_404(db_session, task_id, current_user)
    dependents = await find_task_node_dependents(
        db_session,
        task=task,
        task_node_id=task_node_id,
    )
    return [NodeDependentResponse.model_validate(node) for node in dependents]


@router.get("/{task_id}/node-logs", response_model=list[NodeLogResponse])
async def list_node_logs(
    task_id: uuid.UUID,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
    node_id: uuid.UUID | None = None,
    status: NodeLogStatus | None = None,
    trigger_type: NodeLogTriggerType | None = None,
) -> list[NodeLog]:
    """
    Раздел 13.4: история выполнения — лента и вкладка «Логи» с фильтрами
    по ноде, статусу и источнику.
    """
    await get_task_or_404(db_session, task_id, current_user)
    return await filter_node_logs(
        db_session,
        task_id,
        node_id=node_id,
        status=status,
        trigger_type=trigger_type,
    )
