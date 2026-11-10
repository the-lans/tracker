"""Состояние лимита LLM-аккаунтов для списка «LLM-аккаунты» (разделы 15.1, 19.7 ТЗ)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest

from db.models.enums import (
    LlmAccountStatus,
    NodeLogStatus,
    NodeLogTriggerType,
    TaskStatus,
)
from db.models.logs import NodeLog
from services.llm_account_choice import LimitState
from services.llm_limit_state import account_limit_states
from tests.factories import make_llm_account, make_task, make_user

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

_NOW = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
_RESET = _NOW + timedelta(hours=2)


class TestAccountLimitStates:
    @pytest.mark.parametrize(
        ("status", "usage", "week", "state", "until"),
        [
            (LlmAccountStatus.ACTIVE, None, None, LimitState.FREE, None),
            (LlmAccountStatus.ACTIVE, "40", None, LimitState.RUNNING, _RESET),
            (LlmAccountStatus.ACTIVE, "90", None, LimitState.AT_THRESHOLD, _RESET),
            (LlmAccountStatus.ACTIVE, "40", "100", LimitState.EXHAUSTED, None),
            (LlmAccountStatus.DISABLED, "40", None, LimitState.EXCLUDED, None),
        ],
        ids=["free", "running", "at_threshold", "week_exhausted", "disabled"],
    )
    async def test_state(
        self,
        db_session: AsyncSession,
        status: LlmAccountStatus,
        usage: str | None,
        week: str | None,
        state: LimitState,
        until: datetime | None,
    ) -> None:
        owner = await make_user(db_session)
        owner.llm_switch_threshold_5h_pct = 90
        account = await make_llm_account(db_session, owner_id=owner.id, status=status)
        if usage is not None:
            account.usage_5h_pct = Decimal(usage)
            account.usage_5h_resets_at = _RESET
        account.usage_week_pct = Decimal(week) if week is not None else None
        await db_session.flush()

        states = await account_limit_states(db_session, [account], now=_NOW)

        assert (states[account.id].state, states[account.id].until) == (state, until)

    @pytest.mark.parametrize(
        ("turns", "state"),
        [
            ([NodeLogStatus.RUNNING], LimitState.AT_THRESHOLD),
            ([NodeLogStatus.SUCCESS, NodeLogStatus.FAILED], LimitState.RUNNING),
        ],
        ids=["running_turn", "finished_turns"],
    )
    async def test_tasks_and_running_turns(
        self,
        db_session: AsyncSession,
        turns: list[NodeLogStatus],
        state: LimitState,
    ) -> None:
        """Задачи в работе на аккаунте; идущий ход резервирует расход до порога."""
        owner = await make_user(db_session)
        owner.llm_switch_threshold_5h_pct = 93
        account = await make_llm_account(db_session, owner_id=owner.id)
        account.usage_5h_pct = Decimal("92.5")
        account.usage_5h_resets_at = _RESET
        working = await make_task(
            db_session,
            created_by=owner.id,
            status=TaskStatus.IN_PROGRESS,
            current_llm_account_id=account.id,
        )
        await make_task(
            db_session,
            created_by=owner.id,
            status=TaskStatus.DONE,
            current_llm_account_id=account.id,
        )
        for status in turns:
            db_session.add(
                NodeLog(
                    task_id=working.id,
                    trigger_type=NodeLogTriggerType.PIPELINE,
                    status=status,
                    llm_account_id=account.id,
                ),
            )
        await db_session.flush()

        info = (await account_limit_states(db_session, [account], now=_NOW))[account.id]

        assert (info.state, info.active_tasks) == (state, 1)

    async def test_threshold_of_each_owner(self, db_session: AsyncSession) -> None:
        strict, lenient = await make_user(db_session), await make_user(db_session)
        strict.llm_switch_threshold_5h_pct = 50
        lenient.llm_switch_threshold_5h_pct = 95
        accounts = [
            await make_llm_account(db_session, owner_id=owner.id) for owner in (strict, lenient)
        ]
        for account in accounts:
            account.usage_5h_pct = Decimal("60")
            account.usage_5h_resets_at = _RESET
        await db_session.flush()

        states = await account_limit_states(db_session, accounts, now=_NOW)

        assert [states[account.id].state for account in accounts] == [
            LimitState.AT_THRESHOLD,
            LimitState.RUNNING,
        ]

    async def test_empty(self, db_session: AsyncSession) -> None:
        assert await account_limit_states(db_session, [], now=_NOW) == {}
