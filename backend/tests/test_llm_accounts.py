"""Тесты `services/llm_accounts.py` (раздел 16.2 ТЗ, `check_llm_account_limits`)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from claude_agent_sdk import RateLimitInfo
from claude_agent_sdk.types import RateLimitStatus

from db.models.enums import LlmAccountStatus
from db.models.llm import LlmAccount
from services.llm_accounts import record_rate_limit, restore_expired_rate_limits

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

_RESETS_AT = datetime(2026, 10, 20, 18, 0, tzinfo=UTC)


async def _account(db_session: AsyncSession, status: LlmAccountStatus) -> LlmAccount:
    account = LlmAccount(label="main", claude_config_dir="/tmp/acc", status=status)
    db_session.add(account)
    await db_session.flush()
    return account


class TestRecordRateLimit:
    @pytest.mark.parametrize(
        ("start", "event_status", "expected", "resets_at"),
        [
            (LlmAccountStatus.ACTIVE, "rejected", LlmAccountStatus.RATE_LIMITED, _RESETS_AT),
            (LlmAccountStatus.RATE_LIMITED, "allowed", LlmAccountStatus.ACTIVE, None),
            (LlmAccountStatus.ACTIVE, "allowed_warning", LlmAccountStatus.ACTIVE, None),
            (LlmAccountStatus.DISABLED, "rejected", LlmAccountStatus.DISABLED, None),
        ],
        ids=["rejected", "allowed_again", "warning_only", "disabled_untouched"],
    )
    async def test_status(
        self,
        db_session: AsyncSession,
        start: LlmAccountStatus,
        event_status: RateLimitStatus,
        expected: LlmAccountStatus,
        resets_at: datetime | None,
    ) -> None:
        account = await _account(db_session, start)
        info = RateLimitInfo(
            status=event_status,
            resets_at=int(_RESETS_AT.timestamp()),
        )

        await record_rate_limit(db_session, account_id=account.id, info=info)

        assert account.status is expected
        assert account.rate_limit_resets_at == resets_at


class TestRestoreExpiredRateLimits:
    async def test_only_expired_windows(self, db_session: AsyncSession) -> None:
        now = datetime.now(UTC)
        expired = await _account(db_session, LlmAccountStatus.RATE_LIMITED)
        expired.rate_limit_resets_at = now - timedelta(minutes=1)
        pending = await _account(db_session, LlmAccountStatus.RATE_LIMITED)
        pending.rate_limit_resets_at = now + timedelta(hours=1)
        await db_session.flush()

        restored = await restore_expired_rate_limits(db_session, now=now)

        assert restored == [expired.id]
        await db_session.refresh(expired)
        await db_session.refresh(pending)
        assert expired.status is LlmAccountStatus.ACTIVE
        assert pending.status is LlmAccountStatus.RATE_LIMITED
