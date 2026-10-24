"""Импорт задачи из Jira (раздел 15.6 ТЗ): черновик формы новой задачи по ключу."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_current_user
from api.schemas import JiraIssueDraftResponse, JiraServerResponse
from db.models.users import User
from db.session import get_session
from services.jira_import import JiraIssueDraft, fetch_jira_draft, new_jira_http_client
from services.system_settings import get_jira_url

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
