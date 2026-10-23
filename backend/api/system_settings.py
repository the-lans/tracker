"""
«Системные настройки» (раздел 15.5 ТЗ): чтение — любому пользователю (форме
ноды нужны значения по умолчанию), изменение — только администратору.
Интеграция с GitLab — только администратору и без значения токена.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_current_user, require_admin
from api.schemas import (
    GitlabIntegrationResponse,
    GitlabIntegrationUpdateRequest,
    SystemSettingsBody,
)
from db.models.settings import SystemSettings
from db.models.users import User
from db.session import get_session
from services.system_settings import (
    SystemSettingsValues,
    get_system_settings,
    update_gitlab_integration,
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


def _gitlab_integration(settings: SystemSettings) -> GitlabIntegrationResponse:
    return GitlabIntegrationResponse(
        gitlab_url=settings.gitlab_url,
        gitlab_token_set=settings.gitlab_token_encrypted is not None,
    )


@router.get("/integrations", response_model=GitlabIntegrationResponse)
async def read_integrations(
    db_session: Annotated[AsyncSession, Depends(get_session)],
    _admin: Annotated[User, Depends(require_admin)],
) -> GitlabIntegrationResponse:
    return _gitlab_integration(await get_system_settings(db_session))


@router.put("/integrations", response_model=GitlabIntegrationResponse)
async def replace_integrations(
    body: GitlabIntegrationUpdateRequest,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    _admin: Annotated[User, Depends(require_admin)],
) -> GitlabIntegrationResponse:
    settings = await update_gitlab_integration(
        db_session,
        url=body.gitlab_url,
        token=body.gitlab_token,
    )
    return _gitlab_integration(settings)
