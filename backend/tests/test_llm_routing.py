"""Токен сессии, маршрут хода и выбор аккаунта задачи (раздел 19.7 ТЗ)."""

from __future__ import annotations

import asyncio
import uuid
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import pytest

from db.models.enums import LlmAccountStatus, LlmSwitchReason, ReasoningEffort
from db.models.llm import LlmAccount
from services.llm_routing import (
    SESSION_TOKEN_TTL_SECONDS,
    NoLlmAccountAvailableError,
    SwitchThresholds,
    TurnRoute,
    choose_account,
    issue_session_token,
    llm_session_token,
    publish_route,
    read_route,
    renew_session_token,
    resolve_session_token,
    revoke_session_token,
)

if TYPE_CHECKING:
    from redis.asyncio import Redis

_THRESHOLDS = SwitchThresholds(five_hour=93, week=90)
_ACTIVE = LlmAccountStatus.ACTIVE


def _route(task_id: uuid.UUID | None = None) -> TurnRoute:
    return TurnRoute(
        account_id=task_id or uuid.uuid4(),
        prefix="acc-0123456789ab",
        model="gpt-6-sol",
        effort=ReasoningEffort.MAX,
        provider_effort=ReasoningEffort.XHIGH,
    )


class TestSessionToken:
    async def test_resolves_to_task(self, redis_client: Redis) -> None:
        task_id = uuid.uuid4()

        token = await issue_session_token(redis_client, task_id)

        assert len(token) >= 43
        assert await resolve_session_token(redis_client, token) == task_id
        assert await redis_client.get(f"llm:session:{token}") is None

    async def test_unknown_token(self, redis_client: Redis) -> None:
        assert await resolve_session_token(redis_client, "forged") is None

    async def test_renew_extends_token_and_route(self, redis_client: Redis) -> None:
        task_id = uuid.uuid4()
        token = await issue_session_token(redis_client, task_id)
        await publish_route(redis_client, task_id, _route())
        await redis_client.expire(f"llm:route:{task_id}", 5)

        await renew_session_token(redis_client, task_id=task_id, token=token)

        assert await redis_client.ttl(f"llm:route:{task_id}") > 5

    async def test_revoke_drops_token_and_route(self, redis_client: Redis) -> None:
        task_id = uuid.uuid4()
        token = await issue_session_token(redis_client, task_id)
        await publish_route(redis_client, task_id, _route())

        await revoke_session_token(redis_client, task_id=task_id, token=token)

        assert await resolve_session_token(redis_client, token) is None
        assert await read_route(redis_client, task_id) is None


class TestSessionTokenScope:
    async def test_renewed_then_revoked(self, redis_client: Redis) -> None:
        task_id = uuid.uuid4()

        async with llm_session_token(redis_client, task_id, interval=0.01) as token:
            await publish_route(redis_client, task_id, _route())
            await redis_client.expire(f"llm:route:{task_id}", 5)
            await asyncio.sleep(0.05)
            assert await redis_client.ttl(f"llm:route:{task_id}") > 5
            assert await resolve_session_token(redis_client, token) == task_id

        assert await resolve_session_token(redis_client, token) is None
        assert await read_route(redis_client, task_id) is None


class TestRoute:
    async def test_round_trip(self, redis_client: Redis) -> None:
        task_id = uuid.uuid4()
        route = _route()

        await publish_route(redis_client, task_id, route)

        assert await read_route(redis_client, task_id) == route
        assert 0 < await redis_client.ttl(f"llm:route:{task_id}") <= SESSION_TOKEN_TTL_SECONDS

    async def test_missing(self, redis_client: Redis) -> None:
        assert await read_route(redis_client, uuid.uuid4()) is None


def _account(
    order: int,
    *,
    pct_5h: str | None = None,
    pct_week: str | None = None,
    status: LlmAccountStatus = _ACTIVE,
    provider: str = "anthropic",
    model: str | None = "claude-opus-5-5",
) -> LlmAccount:
    return LlmAccount(
        id=uuid.uuid4(),
        label=f"acc-{order}",
        provider=provider,
        status=status,
        switch_order=order,
        default_model=model,
        usage_5h_pct=Decimal(pct_5h) if pct_5h else None,
        usage_week_pct=Decimal(pct_week) if pct_week else None,
    )


def _choose(
    accounts: list[LlmAccount],
    *,
    current: LlmAccount | None = None,
    start: LlmAccount | None = None,
    plan_prompt: bool = False,
) -> tuple[LlmAccount, LlmSwitchReason]:
    choice = choose_account(
        accounts,
        current_id=current.id if current else None,
        start_id=start.id if start else None,
        thresholds=_THRESHOLDS,
        plan_prompt=plan_prompt,
    )
    return choice.account, choice.reason


class TestFirstCall:
    def test_start_account_below_threshold(self) -> None:
        first, start = _account(1), _account(2, pct_5h="50")

        assert _choose([first, start], start=start) == (start, LlmSwitchReason.START)

    @pytest.mark.parametrize(
        ("start_fields", "reason"),
        [
            ({"pct_5h": "93"}, LlmSwitchReason.THRESHOLD_5H),
            ({"pct_week": "95.5"}, LlmSwitchReason.THRESHOLD_WEEK),
            ({"status": LlmAccountStatus.RATE_LIMITED}, LlmSwitchReason.RATE_LIMITED),
            ({"status": LlmAccountStatus.LOGIN_REQUIRED}, LlmSwitchReason.LOGIN_REQUIRED),
            ({"status": LlmAccountStatus.DISABLED}, LlmSwitchReason.DISABLED),
            ({"model": None}, LlmSwitchReason.UNSUITABLE),
        ],
    )
    def test_start_account_skipped(
        self,
        start_fields: dict[str, Any],
        reason: LlmSwitchReason,
    ) -> None:
        start = _account(1, **start_fields)
        second = _account(2)

        assert _choose([start, second], start=start) == (second, reason)

    def test_without_start_account(self) -> None:
        first = _account(1)

        assert _choose([first, _account(2)]) == (first, LlmSwitchReason.START)


class TestCurrentAccount:
    @pytest.mark.parametrize(("pct_5h", "pct_week"), [("92.99", "89.99"), (None, None)])
    def test_kept_below_threshold(self, pct_5h: str | None, pct_week: str | None) -> None:
        first = _account(1)
        current = _account(2, pct_5h=pct_5h, pct_week=pct_week)

        assert _choose([first, current], current=current, start=first) == (
            current,
            LlmSwitchReason.KEPT,
        )

    @pytest.mark.parametrize(
        ("current_fields", "reason"),
        [
            ({"pct_5h": "93.00"}, LlmSwitchReason.THRESHOLD_5H),
            ({"pct_week": "90"}, LlmSwitchReason.THRESHOLD_WEEK),
            ({"status": LlmAccountStatus.RATE_LIMITED}, LlmSwitchReason.RATE_LIMITED),
        ],
    )
    def test_switch_to_first_below(
        self,
        current_fields: dict[str, Any],
        reason: LlmSwitchReason,
    ) -> None:
        full = _account(1, pct_5h="99")
        current = _account(2, **current_fields)
        third, fourth = _account(3), _account(4)

        assert _choose([full, current, third, fourth], current=current) == (third, reason)

    def test_switch_back_to_earlier_account(self) -> None:
        first = _account(1, pct_5h="10")
        current = _account(2, pct_5h="94")

        assert _choose([first, current], current=current) == (first, LlmSwitchReason.THRESHOLD_5H)


class TestAllAboveThreshold:
    def test_least_used_window(self) -> None:
        current = _account(1, pct_5h="97", pct_week="20")
        least = _account(2, pct_5h="94", pct_week="95")
        other = _account(3, pct_5h="99")

        assert _choose([current, least, other], current=current) == (
            least,
            LlmSwitchReason.ALL_ABOVE_THRESHOLD,
        )

    def test_tie_keeps_switch_order(self) -> None:
        first, second = _account(1, pct_5h="95"), _account(2, pct_5h="95")

        assert _choose([first, second], current=second)[0] is first


class TestPlanPrompt:
    def test_provider_without_plan_skipped(self) -> None:
        current = _account(1, provider="google")
        codex = _account(2, provider="openai")

        assert _choose([current, codex], current=current, plan_prompt=True) == (
            codex,
            LlmSwitchReason.UNSUITABLE,
        )

    def test_provider_without_plan_kept_for_other_nodes(self) -> None:
        current = _account(1, provider="google")

        assert _choose([current], current=current)[1] is LlmSwitchReason.KEPT


class TestNoAccount:
    @pytest.mark.parametrize(
        ("accounts", "plan_prompt"),
        [
            ([], False),
            ([_account(1, status=LlmAccountStatus.RATE_LIMITED)], False),
            ([_account(1, model=None), _account(2, provider="mistral")], False),
            ([_account(1, provider="xai")], True),
        ],
        ids=["none", "rate_limited", "unsuitable", "plan_prompt"],
    )
    def test_raises(self, accounts: list[LlmAccount], plan_prompt: bool) -> None:
        with pytest.raises(NoLlmAccountAvailableError):
            _choose(accounts, plan_prompt=plan_prompt)
