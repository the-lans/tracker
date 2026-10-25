"""
Переменные окружения уровня задачи (раздел 10.3 ТЗ).
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_current_user
from api.schemas import (
    EnvVariableRevealResponse,
    TaskEnvVariableCreateRequest,
    TaskEnvVariableResponse,
    TaskEnvVariableUpdateRequest,
)
from api.tasks.common import TASKS_PREFIX, TASKS_TAGS, get_task_or_404
from db.models.env_vars import TaskEnvVariable
from db.models.users import User
from db.session import get_session
from services.task_env_variables import (
    create_task_env_variable,
    delete_task_env_variable,
    list_task_env_variables,
    reveal_task_env_variable,
    update_task_env_variable,
)

router = APIRouter(prefix=TASKS_PREFIX, tags=TASKS_TAGS)


@router.get("/{task_id}/env-variables", response_model=list[TaskEnvVariableResponse])
async def list_env_variables_of_task(
    task_id: uuid.UUID,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> list[TaskEnvVariable]:
    """Раздел 15.2: переменные в зоне статичных данных задачи."""
    task = await get_task_or_404(db_session, task_id, current_user)
    return await list_task_env_variables(db_session, task)


@router.post(
    "/{task_id}/env-variables",
    response_model=TaskEnvVariableResponse,
    status_code=201,
)
async def create_env_variable_of_task(
    task_id: uuid.UUID,
    body: TaskEnvVariableCreateRequest,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> TaskEnvVariable:
    task = await get_task_or_404(db_session, task_id, current_user)
    return await create_task_env_variable(
        db_session,
        task=task,
        key=body.key,
        value=body.value,
    )


@router.patch(
    "/{task_id}/env-variables/{variable_id}",
    response_model=TaskEnvVariableResponse,
)
async def update_env_variable_of_task(
    task_id: uuid.UUID,
    variable_id: uuid.UUID,
    body: TaskEnvVariableUpdateRequest,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> TaskEnvVariable:
    task = await get_task_or_404(db_session, task_id, current_user)
    return await update_task_env_variable(
        db_session,
        task=task,
        variable_id=variable_id,
        value=body.value,
    )


@router.delete("/{task_id}/env-variables/{variable_id}", status_code=204)
async def delete_env_variable_of_task(
    task_id: uuid.UUID,
    variable_id: uuid.UUID,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> None:
    task = await get_task_or_404(db_session, task_id, current_user)
    await delete_task_env_variable(db_session, task=task, variable_id=variable_id)


@router.get(
    "/{task_id}/env-variables/{variable_id}/reveal",
    response_model=EnvVariableRevealResponse,
)
async def reveal_env_variable_of_task(
    task_id: uuid.UUID,
    variable_id: uuid.UUID,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> EnvVariableRevealResponse:
    """Правило 8: значение — только по явному запросу «Показать»."""
    task = await get_task_or_404(db_session, task_id, current_user)
    value = await reveal_task_env_variable(db_session, task=task, variable_id=variable_id)
    return EnvVariableRevealResponse(value=value)
