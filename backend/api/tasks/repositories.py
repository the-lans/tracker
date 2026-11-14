"""Репозитории задачи после её создания (раздел 3.2 ТЗ)."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_current_user
from api.schemas import TaskRepositoriesAddRequest, TaskRepositoryResponse
from api.tasks.common import TASKS_PREFIX, TASKS_TAGS, get_task_or_404, publish_signal
from db.models.tasks import TaskRepository
from db.models.users import User
from db.session import get_session
from services.task_repositories import (
    RepositoryAttachment,
    add_task_repositories,
    remove_task_repository,
)

router = APIRouter(prefix=TASKS_PREFIX, tags=TASKS_TAGS)


@router.post(
    "/{task_id}/repositories",
    response_model=list[TaskRepositoryResponse],
    status_code=201,
)
async def add_repositories(
    task_id: uuid.UUID,
    body: TaskRepositoriesAddRequest,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> list[TaskRepository]:
    """Клонирует воркер: до следующей ноды или при следующем запуске и ходе чата."""
    task = await get_task_or_404(db_session, task_id, current_user)
    added = await add_task_repositories(
        db_session,
        task=task,
        attachments=[
            RepositoryAttachment(
                repository_id=attached.repository_id,
                role=attached.role,
                base_branch=attached.base_branch,
            )
            for attached in body.repositories
        ],
    )
    # Задача на паузе ждёт сигнала — клон не должен ждать «Продолжить».
    await publish_signal(task.id)
    return added


@router.delete("/{task_id}/repositories/{task_repository_id}", status_code=204)
async def remove_repository(
    task_id: uuid.UUID,
    task_repository_id: uuid.UUID,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> None:
    task = await get_task_or_404(db_session, task_id, current_user)
    await remove_task_repository(db_session, task=task, task_repository_id=task_repository_id)
