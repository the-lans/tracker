"""Импорт задачи из Jira (раздел 15.6 ТЗ): черновик формы новой задачи по ключу."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends

from api.dependencies import get_current_user
from api.schemas import JiraIssueDraftResponse
from db.models.users import User
from services.jira_import import JiraIssueDraft, fetch_jira_draft

router = APIRouter(prefix="/jira", tags=["jira"])

# Запрос к Jira — по действию пользователя: ждать дольше нет смысла.
_JIRA_TIMEOUT_SECONDS = 30.0


async def get_jira_http_client() -> AsyncIterator[httpx.AsyncClient]:
    """HTTP-клиент к Jira на время запроса; тесты подменяют его транспорт."""
    async with httpx.AsyncClient(timeout=_JIRA_TIMEOUT_SECONDS) as client:
        yield client


@router.get("/issues/{key}", response_model=JiraIssueDraftResponse)
async def get_issue_draft(
    key: str,
    current_user: Annotated[User, Depends(get_current_user)],
    http_client: Annotated[httpx.AsyncClient, Depends(get_jira_http_client)],
) -> JiraIssueDraft:
    return await fetch_jira_draft(user=current_user, key=key, http_client=http_client)
