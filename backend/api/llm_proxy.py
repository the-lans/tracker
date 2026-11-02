"""LLM-прокси в администрировании (раздел 15.5 ТЗ, только `admin`)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_cliproxy, require_admin
from api.schemas import ProxyCredentialRequest, ProxyStateResponse
from clients.cliproxy import CliproxyManagementClient
from db.models.users import User
from db.session import get_session
from services.llm_proxy_admin import (
    ProxyState,
    delete_orphan_credential,
    proxy_state,
    refresh_credential,
    reset_cooldown,
)

router = APIRouter(prefix="/llm-proxy", tags=["admin-llm-proxy"])

Admin = Annotated[User, Depends(require_admin)]
Cliproxy = Annotated[CliproxyManagementClient, Depends(get_cliproxy)]


@router.get("", response_model=ProxyStateResponse)
async def get_llm_proxy_state(
    _admin: Admin,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    cliproxy: Cliproxy,
) -> ProxyState:
    return await proxy_state(db_session, cliproxy)


@router.post("/credentials/refresh", status_code=204)
async def refresh_llm_proxy_credential(
    body: ProxyCredentialRequest,
    _admin: Admin,
    cliproxy: Cliproxy,
) -> None:
    """Обновить токен учётки (`POST /credentials/refresh`)."""
    await refresh_credential(cliproxy, body.name)


@router.post("/credentials/cooldown/reset", status_code=204)
async def reset_llm_proxy_cooldown(
    body: ProxyCredentialRequest,
    _admin: Admin,
    cliproxy: Cliproxy,
) -> None:
    """Снять паузу учётки после ошибки (`POST /routing/cooldown/reset`)."""
    await reset_cooldown(cliproxy, body.name)


@router.delete("/credentials", status_code=204)
async def delete_llm_proxy_credential(
    _admin: Admin,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    cliproxy: Cliproxy,
    name: Annotated[str, Query(min_length=1)],
) -> None:
    """Удалить учётку «без владельца»."""
    await delete_orphan_credential(db_session, cliproxy, name)
