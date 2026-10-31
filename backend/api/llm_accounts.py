"""
LLM-аккаунты (разделы 3.1, 15.1, 19.5 ТЗ).

Раздел 19.2 (решение №17 плана): аккаунт личный — `user` заводит свои
аккаунты и видит только их, `admin` — аккаунты всех пользователей. Вход в
аккаунт выполняет сам пользователь через LLM-прокси: трекер выдаёт ссылку,
пользователь вставляет адрес, на который вернулся браузер.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated

import sqlalchemy as sa
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_cliproxy, get_current_user
from api.schemas import (
    LlmAccountCreateRequest,
    LlmAccountOrderRequest,
    LlmAccountResponse,
    LlmAccountUpdateRequest,
    LlmLoginCallbackRequest,
    LlmLoginStartResponse,
    LlmLoginStatusResponse,
    LlmProviderResponse,
)
from clients.cliproxy import CliproxyManagementClient
from db.models.llm import LlmAccount
from db.models.users import User
from db.session import get_session
from services.access import get_llm_account_for_user, owner_filter
from services.llm_account_login import (
    LoginResult,
    LoginStart,
    cancel_login,
    poll_login,
    start_login,
    submit_login_callback,
)
from services.llm_accounts import (
    account_models,
    create_account,
    delete_account,
    ensure_model_available,
    reorder_accounts,
    set_account_enabled,
)
from services.llm_providers import PROVIDERS
from services.redis_connection import redis_connection

router = APIRouter(prefix="/llm-accounts", tags=["llm-accounts"])

Cliproxy = Annotated[CliproxyManagementClient, Depends(get_cliproxy)]
DbSession = Annotated[AsyncSession, Depends(get_session)]
CurrentUser = Annotated[User, Depends(get_current_user)]


@router.get("/providers", response_model=list[LlmProviderResponse])
async def list_llm_providers(_: CurrentUser) -> list[LlmProviderResponse]:
    """Раздел 19.7: провайдеры реестра трекера для формы аккаунта."""
    return [
        LlmProviderResponse(
            id=provider.id,
            label=provider.label,
            reports_usage=provider.usage_source is not None,
            plan_prompt_allowed=provider.plan_prompt_allowed,
        )
        for provider in PROVIDERS.values()
    ]


@router.post("", response_model=LlmAccountResponse, status_code=201)
async def create_llm_account(
    body: LlmAccountCreateRequest,
    db_session: DbSession,
    current_user: CurrentUser,
) -> LlmAccount:
    return await create_account(
        db_session,
        owner_id=current_user.id,
        label=body.label,
        provider=body.provider,
    )


@router.get("", response_model=list[LlmAccountResponse])
async def list_llm_accounts(db_session: DbSession, current_user: CurrentUser) -> list[LlmAccount]:
    """Раздел 15.1: в порядке переключения (у admin — по владельцам)."""
    stmt = (
        sa.select(LlmAccount)
        .where(owner_filter(LlmAccount.created_by, current_user))
        .order_by(LlmAccount.created_by, LlmAccount.switch_order)
    )
    return list((await db_session.execute(stmt)).scalars().all())


@router.put("/order", response_model=list[LlmAccountResponse])
async def reorder_llm_accounts(
    body: LlmAccountOrderRequest,
    db_session: DbSession,
    current_user: CurrentUser,
) -> list[LlmAccount]:
    """Раздел 15.1: порядок переключения своих аккаунтов (кнопки ↑/↓)."""
    return await reorder_accounts(
        db_session,
        owner_id=current_user.id,
        account_ids=body.account_ids,
    )


@router.get("/{llm_account_id}", response_model=LlmAccountResponse)
async def get_llm_account(
    llm_account_id: uuid.UUID,
    db_session: DbSession,
    current_user: CurrentUser,
) -> LlmAccount:
    return await get_llm_account_for_user(db_session, llm_account_id, user=current_user)


@router.patch("/{llm_account_id}", response_model=LlmAccountResponse)
async def update_llm_account(
    llm_account_id: uuid.UUID,
    body: LlmAccountUpdateRequest,
    db_session: DbSession,
    current_user: CurrentUser,
    cliproxy: Cliproxy,
) -> LlmAccount:
    llm_account = await get_llm_account_for_user(db_session, llm_account_id, user=current_user)
    if body.default_model is not None:
        await ensure_model_available(cliproxy, llm_account, body.default_model)
        llm_account.default_model = body.default_model
    if body.label is not None:
        llm_account.label = body.label
    if body.default_effort is not None:
        llm_account.default_effort = body.default_effort
    if body.enabled is not None:
        await set_account_enabled(
            db_session,
            cliproxy,
            llm_account,
            enabled=body.enabled,
            now=datetime.now(UTC),
        )
    await db_session.commit()
    await db_session.refresh(llm_account)
    return llm_account


@router.delete("/{llm_account_id}", status_code=204)
async def delete_llm_account(
    llm_account_id: uuid.UUID,
    db_session: DbSession,
    current_user: CurrentUser,
    cliproxy: Cliproxy,
) -> None:
    llm_account = await get_llm_account_for_user(db_session, llm_account_id, user=current_user)
    await delete_account(db_session, cliproxy, llm_account)
    async with redis_connection() as redis_client:
        await cancel_login(redis_client, cliproxy, llm_account)


@router.get("/{llm_account_id}/models", response_model=list[str])
async def list_llm_account_models(
    llm_account_id: uuid.UUID,
    db_session: DbSession,
    current_user: CurrentUser,
    cliproxy: Cliproxy,
) -> list[str]:
    """Раздел 15.1: модели учётки аккаунта для выбора модели по умолчанию."""
    llm_account = await get_llm_account_for_user(db_session, llm_account_id, user=current_user)
    return await account_models(cliproxy, llm_account)


@router.post("/{llm_account_id}/login", response_model=LlmLoginStartResponse)
async def start_llm_account_login(
    llm_account_id: uuid.UUID,
    db_session: DbSession,
    current_user: CurrentUser,
    cliproxy: Cliproxy,
) -> LoginStart:
    """Раздел 19.5: ссылка входа у провайдера; повторный вход — в учётку этого аккаунта."""
    llm_account = await get_llm_account_for_user(db_session, llm_account_id, user=current_user)
    async with redis_connection() as redis_client:
        return await start_login(redis_client, cliproxy, llm_account, now=datetime.now(UTC))


@router.post("/{llm_account_id}/login/callback", response_model=LlmLoginStatusResponse)
async def submit_llm_account_login(
    llm_account_id: uuid.UUID,
    body: LlmLoginCallbackRequest,
    db_session: DbSession,
    current_user: CurrentUser,
    cliproxy: Cliproxy,
) -> LoginResult:
    """Адрес, на который вернулся браузер после входа; ответ — итог входа или `wait`."""
    llm_account = await get_llm_account_for_user(db_session, llm_account_id, user=current_user)
    async with redis_connection() as redis_client:
        return await submit_login_callback(
            db_session,
            redis_client,
            cliproxy,
            llm_account,
            redirect_url=body.redirect_url,
            now=datetime.now(UTC),
        )


@router.get("/{llm_account_id}/login/status", response_model=LlmLoginStatusResponse)
async def get_llm_account_login_status(
    llm_account_id: uuid.UUID,
    db_session: DbSession,
    current_user: CurrentUser,
    cliproxy: Cliproxy,
) -> LoginResult:
    llm_account = await get_llm_account_for_user(db_session, llm_account_id, user=current_user)
    async with redis_connection() as redis_client:
        return await poll_login(
            db_session,
            redis_client,
            cliproxy,
            llm_account,
            now=datetime.now(UTC),
        )


@router.delete("/{llm_account_id}/login", status_code=204)
async def cancel_llm_account_login(
    llm_account_id: uuid.UUID,
    db_session: DbSession,
    current_user: CurrentUser,
    cliproxy: Cliproxy,
) -> None:
    llm_account = await get_llm_account_for_user(db_session, llm_account_id, user=current_user)
    async with redis_connection() as redis_client:
        await cancel_login(redis_client, cliproxy, llm_account)
