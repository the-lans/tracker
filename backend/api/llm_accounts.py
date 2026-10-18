"""CRUD `llm_accounts` (раздел 3.1 ТЗ) — административная часть (раздел
15.5 ТЗ): управление аккаунтами Claude Code, от которых запускаются сессии
задач, требует роли admin (раздел 19.2)."""

from __future__ import annotations

import uuid
from typing import Annotated

import sqlalchemy as sa
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import require_admin
from api.schemas import LlmAccountCreateRequest, LlmAccountResponse, LlmAccountUpdateRequest
from db.models.llm import LlmAccount
from db.models.users import User
from db.session import get_session
from services.errors import NotFoundError

router = APIRouter(prefix="/llm-accounts", tags=["llm-accounts"])


async def _get_llm_account_or_404(
    db_session: AsyncSession,
    llm_account_id: uuid.UUID,
) -> LlmAccount:
    llm_account = await db_session.get(LlmAccount, llm_account_id)
    if llm_account is None:
        raise NotFoundError(f"LLM-аккаунт {llm_account_id} не найден")
    return llm_account


@router.post("", response_model=LlmAccountResponse, status_code=201)
async def create_llm_account(
    body: LlmAccountCreateRequest,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    _admin: Annotated[User, Depends(require_admin)],
) -> LlmAccount:
    llm_account = LlmAccount(
        id=uuid.uuid4(),
        label=body.label,
        claude_config_dir=body.claude_config_dir,
        status=body.status,
    )
    db_session.add(llm_account)
    await db_session.commit()
    return llm_account


@router.get("", response_model=list[LlmAccountResponse])
async def list_llm_accounts(
    db_session: Annotated[AsyncSession, Depends(get_session)],
    _admin: Annotated[User, Depends(require_admin)],
) -> list[LlmAccount]:
    stmt = sa.select(LlmAccount).order_by(LlmAccount.label)
    return list((await db_session.execute(stmt)).scalars().all())


@router.get("/{llm_account_id}", response_model=LlmAccountResponse)
async def get_llm_account(
    llm_account_id: uuid.UUID,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    _admin: Annotated[User, Depends(require_admin)],
) -> LlmAccount:
    return await _get_llm_account_or_404(db_session, llm_account_id)


@router.patch("/{llm_account_id}", response_model=LlmAccountResponse)
async def update_llm_account(
    llm_account_id: uuid.UUID,
    body: LlmAccountUpdateRequest,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    _admin: Annotated[User, Depends(require_admin)],
) -> LlmAccount:
    llm_account = await _get_llm_account_or_404(db_session, llm_account_id)
    if body.label is not None:
        llm_account.label = body.label
    if body.claude_config_dir is not None:
        llm_account.claude_config_dir = body.claude_config_dir
    if body.status is not None:
        llm_account.status = body.status
    await db_session.commit()
    await db_session.refresh(llm_account)
    return llm_account


@router.delete("/{llm_account_id}", status_code=204)
async def delete_llm_account(
    llm_account_id: uuid.UUID,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    _admin: Annotated[User, Depends(require_admin)],
) -> None:
    llm_account = await _get_llm_account_or_404(db_session, llm_account_id)
    await db_session.delete(llm_account)
    await db_session.commit()
