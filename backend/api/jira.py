"""Импорт задачи из Jira (раздел 15.6 ТЗ): черновик формы новой задачи по ключу."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_current_user
from api.schemas import JiraIssueDraftResponse, JiraServerResponse, TaskResponse
from api.tasks.common import get_task_or_404
from db.models.tasks import Task
from db.models.users import User
from db.session import get_session
from services.jira_import import (
    JiraIssueDraft,
    fetch_jira_draft,
    mark_attachment_copy_pending,
    new_jira_http_client,
    refresh_description_html,
)
from services.redis_connection import redis_connection
from services.system_settings import get_jira_url
from tasks.jira_attachments import copy_jira_attachments_to_task

router = APIRouter(prefix="/jira", tags=["jira"])


async def get_jira_http_client() -> AsyncIterator[httpx.AsyncClient]:
    """HTTP-клиент к Jira на время запроса; тесты подменяют его транспорт."""
    async with new_jira_http_client() as client:
        yield client


@router.get("/server", response_model=JiraServerResponse)
async def get_jira_server(
    db_session: Annotated[AsyncSession, Depends(get_session)],
    _current_user: Annotated[User, Depends(get_current_user)],
) -> JiraServerResponse:
    """
    Адрес Jira из «Системных настроек» — для подсказок в профиле и форме задачи.
    """
    return JiraServerResponse(jira_url=await get_jira_url(db_session))


@router.get("/issues/{key}", response_model=JiraIssueDraftResponse)
async def get_issue_draft(
    key: str,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
    http_client: Annotated[httpx.AsyncClient, Depends(get_jira_http_client)],
) -> JiraIssueDraft:
    return await fetch_jira_draft(
        db_session,
        user=current_user,
        key=key,
        http_client=http_client,
    )


@router.post("/tasks/{task_id}/description", response_model=TaskResponse)
async def refresh_task_description(
    task_id: uuid.UUID,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
    http_client: Annotated[httpx.AsyncClient, Depends(get_jira_http_client)],
) -> Task:
    """
    Раздел 15.6: «Обновить описание из Jira» — подгружает отрисованное описание
    у задачи, импортированной раньше, и перекопирует вложения для картинок.
    """
    task = await get_task_or_404(db_session, task_id, current_user)
    key = await refresh_description_html(
        db_session,
        task=task,
        user=current_user,
        http_client=http_client,
    )
    async with redis_connection() as redis_client:
        await mark_attachment_copy_pending(redis_client, task.id)
    copy_jira_attachments_to_task.delay(str(task.id), str(current_user.id), key)
    await db_session.refresh(task)
    return task
