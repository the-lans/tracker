"""
Артефакты задачи и копирование вложений Jira (раздел 14.3, 15.6 ТЗ).
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_current_user
from api.schemas import ArtifactResponse, JiraAttachmentCopyResponse
from api.tasks.common import TASKS_PREFIX, TASKS_TAGS, get_task_or_404
from db.models.users import User
from db.session import get_session
from services.jira_import import attachment_copy_pending
from services.redis_connection import redis_connection
from services.task_artifacts import (
    ArtifactInfo,
    artifact_file,
    delete_artifact,
    list_artifacts,
    max_upload_bytes,
    save_artifact,
)

router = APIRouter(prefix=TASKS_PREFIX, tags=TASKS_TAGS)


@router.get("/{task_id}/artifacts", response_model=list[ArtifactResponse])
async def list_task_artifacts(
    task_id: uuid.UUID,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> list[ArtifactInfo]:
    """Раздел 14.3, 15.2: артефакты задачи — в любом её статусе."""
    task = await get_task_or_404(db_session, task_id, current_user)
    return list_artifacts(task.code)


@router.get("/{task_id}/jira-attachments", response_model=JiraAttachmentCopyResponse)
async def get_jira_attachment_copy(
    task_id: uuid.UUID,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> JiraAttachmentCopyResponse:
    """
    Раздел 15.6: идёт ли ещё копирование вложений Jira — пока идёт, страница
    задачи перечитывает список артефактов.
    """
    task = await get_task_or_404(db_session, task_id, current_user)
    async with redis_connection() as redis_client:
        pending = await attachment_copy_pending(redis_client, task.id)
    return JiraAttachmentCopyResponse(pending=pending)


@router.put("/{task_id}/artifacts/{path:path}", response_model=ArtifactResponse, status_code=201)
async def upload_task_artifact(
    task_id: uuid.UUID,
    path: str,
    request: Request,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> ArtifactInfo:
    """Тело запроса — содержимое файла целиком; существующий файл заменяется."""
    task = await get_task_or_404(db_session, task_id, current_user)
    return await save_artifact(task.code, path, request.stream(), max_bytes=max_upload_bytes())


@router.get("/{task_id}/artifacts/{path:path}")
async def download_task_artifact(
    task_id: uuid.UUID,
    path: str,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> FileResponse:
    task = await get_task_or_404(db_session, task_id, current_user)
    target = artifact_file(task.code, path)
    return FileResponse(target, filename=target.name)


@router.delete("/{task_id}/artifacts/{path:path}", status_code=204)
async def delete_task_artifact(
    task_id: uuid.UUID,
    path: str,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> None:
    task = await get_task_or_404(db_session, task_id, current_user)
    delete_artifact(task.code, path)
