"""
Статус лимитов LLM-аккаунта (раздел 16.2 ТЗ, `check_llm_account_limits`).

Отдельного API для опроса лимитов у Claude Agent SDK нет, но CLI сам
присылает в поток сессии `RateLimitEvent` со статусом и временем сброса
окна. Воркер передаёт эти события сюда, а периодическая задача возвращает
аккаунт в `active`, когда окно лимита истекло.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import sqlalchemy as sa

from app_logging.config import get_logger
from db.models.enums import LlmAccountStatus
from db.models.llm import LlmAccount

if TYPE_CHECKING:
    from claude_agent_sdk import RateLimitInfo
    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger("llm_accounts")

_REJECTED = "rejected"


async def record_rate_limit(
    db_session: AsyncSession,
    *,
    account_id: uuid.UUID,
    info: RateLimitInfo,
) -> None:
    """
    `rejected` — аккаунт упёрся в лимит до `resets_at`; иначе — снова `active`.

    Аккаунт, отключённый администратором (`disabled`), не трогается.
    """
    account = await db_session.get(LlmAccount, account_id)
    if account is None or account.status is LlmAccountStatus.DISABLED:
        return
    if info.status == _REJECTED:
        account.status = LlmAccountStatus.RATE_LIMITED
        account.rate_limit_resets_at = (
            datetime.fromtimestamp(info.resets_at, tz=UTC) if info.resets_at else None
        )
    else:
        account.status = LlmAccountStatus.ACTIVE
        account.rate_limit_resets_at = None
    await db_session.commit()
    logger.info(
        "llm_account_rate_limit_recorded",
        account_id=str(account_id),
        status=account.status.value,
        resets_at=account.rate_limit_resets_at,
    )


async def restore_expired_rate_limits(
    db_session: AsyncSession,
    *,
    now: datetime,
) -> list[uuid.UUID]:
    """Периодическая часть: окно лимита истекло — аккаунт снова `active`."""
    stmt = (
        sa.update(LlmAccount)
        .where(
            LlmAccount.status == LlmAccountStatus.RATE_LIMITED,
            LlmAccount.rate_limit_resets_at.is_not(None),
            LlmAccount.rate_limit_resets_at <= now,
        )
        .values(status=LlmAccountStatus.ACTIVE, rate_limit_resets_at=None)
        .returning(LlmAccount.id)
    )
    restored = list((await db_session.execute(stmt)).scalars().all())
    await db_session.commit()
    if restored:
        logger.info("llm_account_rate_limits_restored", account_ids=[str(i) for i in restored])
    return restored
