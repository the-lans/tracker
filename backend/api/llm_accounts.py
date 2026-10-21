"""
CRUD `llm_accounts` (раздел 3.1 ТЗ).

Раздел 19.2 (решение №17 плана): аккаунт личный — `user` заводит свои
аккаунты и видит только их, `admin` — аккаунты всех пользователей. Каталог
конфигурации — внутри корня `CLAUDE_ACCOUNTS_ROOT`; вход в Claude
(`claude auth login`) администратор выполняет в каталоге уже заведённого
аккаунта, поэтому чужой вход не перехватить (раздел 19.5).
"""

from __future__ import annotations

import uuid
from typing import Annotated

import sqlalchemy as sa
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_current_user
from api.schemas import LlmAccountCreateRequest, LlmAccountResponse, LlmAccountUpdateRequest
from db.models.llm import LlmAccount
from db.models.users import User
from db.session import get_session
from services.access import get_llm_account_for_user, owner_filter
from services.errors import ConflictError
from services.integrity import ensure_llm_account_deletable
from services.llm_accounts import validated_config_dir

router = APIRouter(prefix="/llm-accounts", tags=["llm-accounts"])

_CONFIG_DIR_TAKEN_MESSAGE = "Каталог конфигурации уже указан у другого LLM-аккаунта"


async def _commit_unique(db_session: AsyncSession) -> None:
    """Уникальность пути проверена заранее; гонка двух запросов — тоже 409."""
    try:
        await db_session.commit()
    except sa.exc.IntegrityError as exc:
        await db_session.rollback()
        raise ConflictError(_CONFIG_DIR_TAKEN_MESSAGE) from exc


@router.post("", response_model=LlmAccountResponse, status_code=201)
async def create_llm_account(
    body: LlmAccountCreateRequest,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> LlmAccount:
    llm_account = LlmAccount(
        id=uuid.uuid4(),
        label=body.label,
        claude_config_dir=await validated_config_dir(db_session, body.claude_config_dir),
        status=body.status,
        created_by=current_user.id,
    )
    db_session.add(llm_account)
    await _commit_unique(db_session)
    return llm_account


@router.get("", response_model=list[LlmAccountResponse])
async def list_llm_accounts(
    db_session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> list[LlmAccount]:
    stmt = (
        sa.select(LlmAccount)
        .where(owner_filter(LlmAccount.created_by, current_user))
        .order_by(LlmAccount.label)
    )
    return list((await db_session.execute(stmt)).scalars().all())


@router.get("/{llm_account_id}", response_model=LlmAccountResponse)
async def get_llm_account(
    llm_account_id: uuid.UUID,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> LlmAccount:
    return await get_llm_account_for_user(db_session, llm_account_id, user=current_user)


@router.patch("/{llm_account_id}", response_model=LlmAccountResponse)
async def update_llm_account(
    llm_account_id: uuid.UUID,
    body: LlmAccountUpdateRequest,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> LlmAccount:
    llm_account = await get_llm_account_for_user(db_session, llm_account_id, user=current_user)
    if body.label is not None:
        llm_account.label = body.label
    if body.claude_config_dir is not None:
        llm_account.claude_config_dir = await validated_config_dir(
            db_session,
            body.claude_config_dir,
            exclude_account_id=llm_account.id,
        )
    if body.status is not None:
        llm_account.status = body.status
    await _commit_unique(db_session)
    await db_session.refresh(llm_account)
    return llm_account


@router.delete("/{llm_account_id}", status_code=204)
async def delete_llm_account(
    llm_account_id: uuid.UUID,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> None:
    llm_account = await get_llm_account_for_user(db_session, llm_account_id, user=current_user)
    await ensure_llm_account_deletable(db_session, llm_account_id)
    await db_session.delete(llm_account)
    await db_session.commit()
