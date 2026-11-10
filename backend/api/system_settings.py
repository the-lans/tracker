"""
«Системные настройки» (раздел 15.5 ТЗ): чтение — любому пользователю (форме
ноды нужны значения по умолчанию), изменение — только администратору.
Интеграции (GitLab, адрес Jira) — только администратору и без значения токена.
Резервное копирование в S3 (раздел 20.4) — только администратору, секреты
наружу не отдаются.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_current_user, require_admin
from api.schemas import (
    BackupConnectionCheckResponse,
    BackupRunResponse,
    BackupSettingsResponse,
    BackupSettingsUpdateRequest,
    IntegrationsResponse,
    IntegrationsUpdateRequest,
    SystemSettingsBody,
)
from db.models.enums import BackupRunKind
from db.models.settings import SystemSettings
from db.models.users import User
from db.session import get_session
from services.backup.runs import latest_run
from services.backup.settings import (
    BackupSettingsUpdate,
    check_backup_connection,
    update_backup_settings,
)
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
        jira_url=body.jira_url,
    )
    return _integrations(settings)


async def _backup_settings(
    db_session: AsyncSession,
    settings: SystemSettings,
) -> BackupSettingsResponse:
    last_backup = await latest_run(db_session, kind=BackupRunKind.BACKUP)
    last_verify = await latest_run(db_session, kind=BackupRunKind.VERIFY)
    return BackupSettingsResponse(
        enabled=settings.backup_enabled,
        endpoint=settings.backup_s3_endpoint,
        region=settings.backup_s3_region,
        bucket=settings.backup_s3_bucket,
        access_key=settings.backup_s3_access_key,
        secret_key_set=settings.backup_s3_secret_key_encrypted is not None,
        folder=settings.backup_s3_folder,
        retention_count=settings.backup_retention_count,
        passphrase_set=settings.backup_passphrase_encrypted is not None,
        last_backup=BackupRunResponse.model_validate(last_backup) if last_backup else None,
        last_verify=BackupRunResponse.model_validate(last_verify) if last_verify else None,
    )


@router.get("/backup", response_model=BackupSettingsResponse)
async def read_backup_settings(
    db_session: Annotated[AsyncSession, Depends(get_session)],
    _admin: Annotated[User, Depends(require_admin)],
) -> BackupSettingsResponse:
    return await _backup_settings(db_session, await get_system_settings(db_session))


@router.put("/backup", response_model=BackupSettingsResponse)
async def replace_backup_settings(
    body: BackupSettingsUpdateRequest,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    _admin: Annotated[User, Depends(require_admin)],
) -> BackupSettingsResponse:
    settings = await update_backup_settings(
        db_session,
        update=BackupSettingsUpdate(**body.model_dump()),
    )
    return await _backup_settings(db_session, settings)


@router.post("/backup/check", response_model=BackupConnectionCheckResponse)
async def check_backup_settings(
    db_session: Annotated[AsyncSession, Depends(get_session)],
    _admin: Annotated[User, Depends(require_admin)],
) -> BackupConnectionCheckResponse:
    check = await check_backup_connection(db_session)
    return BackupConnectionCheckResponse(ok=check.ok, message=check.message)
