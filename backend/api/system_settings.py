"""
«Системные настройки» (раздел 15.5 ТЗ): чтение — любому пользователю (форме
ноды нужны значения по умолчанию), изменение — только администратору.
Интеграции (GitLab, адрес Jira) — только администратору и без значения токена.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_current_user, require_admin
from api.schemas import (
    IntegrationsResponse,
    IntegrationsUpdateRequest,
    SystemSettingsBody,
)
from db.models.settings import SystemSettings
from db.models.users import User
from db.session import get_session
from services.system_settings import (
    SystemSettingsValues,
    get_system_settings,
    update_integrations,
    update_system_settings,
)

router = APIRouter(prefix="/system-settings", tags=["admin-settings"])


@router.get("", response_model=SystemSettingsBody)
async def read_system_settings(
    db_session: Annotated[AsyncSession, Depends(get_session)],
    _current_user: Annotated[User, Depends(get_current_user)],
) -> SystemSettings:
    return await get_system_settings(db_session)


@router.put("", response_model=SystemSettingsBody)
async def replace_system_settings(
    body: SystemSettingsBody,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    _admin: Annotated[User, Depends(require_admin)],
) -> SystemSettings:
    return await update_system_settings(
        db_session,
        values=SystemSettingsValues(**body.model_dump()),
    )


def _integrations(settings: SystemSettings) -> IntegrationsResponse:
    return IntegrationsResponse(
        gitlab_url=settings.gitlab_url,
        gitlab_token_set=settings.gitlab_token_encrypted is not None,
        jira_url=settings.jira_url,
    )


@router.get("/integrations", response_model=IntegrationsResponse)
async def read_integrations(
    db_session: Annotated[AsyncSession, Depends(get_session)],
    _admin: Annotated[User, Depends(require_admin)],
) -> IntegrationsResponse:
    return _integrations(await get_system_settings(db_session))


@router.put("/integrations", response_model=IntegrationsResponse)
async def replace_integrations(
    body: IntegrationsUpdateRequest,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    _admin: Annotated[User, Depends(require_admin)],
) -> IntegrationsResponse:
    settings = await update_integrations(
        db_session,
        gitlab_url=body.gitlab_url,
        gitlab_token=body.gitlab_token,
        jira_url=body.jira_url,
    )
    return _integrations(settings)
