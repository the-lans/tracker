"""
Расход LLM-аккаунтов для страницы «Мониторинг» (раздел 15.5, 19.7 ТЗ):
доли 5-часового и недельного окна по последнему опросу
(`services/llm_usage.py`) и число автоматических переключений аккаунта
задач за сутки — по записям `app_logs` роутера аккаунтов.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

import sqlalchemy as sa

from db.models.enums import LlmAccountStatus
from db.models.llm import LlmAccount
from db.models.logs import AppLog
from db.models.users import User
from services.account_router import ACCOUNT_ROUTER_LOG_SOURCE, ACCOUNT_SWITCHED_MESSAGE

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

SWITCH_WINDOW = timedelta(days=1)
# Контекст записи о переключении: аккаунт, на который ушла задача.
_SWITCH_TARGET_KEY = "to_account_id"


@dataclass(frozen=True, slots=True)
class AccountUsage:
    id: uuid.UUID
    label: str
    provider: str
    owner_email: str
    status: LlmAccountStatus
    usage_5h_pct: Decimal | None
    usage_week_pct: Decimal | None
    usage_5h_resets_at: datetime | None
    usage_week_resets_at: datetime | None
    usage_checked_at: datetime | None
    switches_to_24h: int


@dataclass(frozen=True, slots=True)
class LlmUsageSummary:
    accounts: list[AccountUsage]
    switches_24h: int


def _switch_filter(*, since: datetime) -> sa.ColumnElement[bool]:
    return sa.and_(
        AppLog.source == ACCOUNT_ROUTER_LOG_SOURCE,
        AppLog.message == ACCOUNT_SWITCHED_MESSAGE,
        AppLog.created_at >= since,
    )


async def _switches_by_target(db_session: AsyncSession, *, since: datetime) -> dict[str, int]:
    target = AppLog.context[_SWITCH_TARGET_KEY].astext
    rows = await db_session.execute(
        sa.select(target, sa.func.count()).where(_switch_filter(since=since)).group_by(target),
    )
    return {str(account_id): count for account_id, count in rows}


async def llm_usage_summary(db_session: AsyncSession, *, now: datetime) -> LlmUsageSummary:
    switches = await _switches_by_target(db_session, since=now - SWITCH_WINDOW)
    rows = await db_session.execute(
        sa.select(LlmAccount, User.email)
        .join(User, User.id == LlmAccount.created_by)
        .order_by(User.email, LlmAccount.switch_order),
    )
    accounts = [
        AccountUsage(
            id=account.id,
            label=account.label,
            provider=account.provider,
            owner_email=email,
            status=account.status,
            usage_5h_pct=account.usage_5h_pct,
            usage_week_pct=account.usage_week_pct,
            usage_5h_resets_at=account.usage_5h_resets_at,
            usage_week_resets_at=account.usage_week_resets_at,
            usage_checked_at=account.usage_checked_at,
            switches_to_24h=switches.get(str(account.id), 0),
        )
        for account, email in rows
    ]
    return LlmUsageSummary(accounts=accounts, switches_24h=sum(switches.values()))
