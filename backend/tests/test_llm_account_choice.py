"""Правило выбора LLM-аккаунта хода: состояния, окна, баланс, ожидание (раздел 19.7 ТЗ)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from db.models.enums import LlmAccountStatus, LlmSwitchReason
from db.models.llm import LlmAccount
from services.llm_account_choice import (
    MIN_LIMIT_WAIT,
    AccountChoice,
    AccountView,
    ChoiceRequest,
    LimitState,
    LimitWait,
    NoLlmAccountAvailableError,
    choose_account,
    limit_state,
    wait_until,
)

_NOW = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)
_THRESHOLD = 93


def _at(hours: float) -> datetime:
    return _NOW + timedelta(hours=hours)


def _account(
    order: int,
    *,
    status: LlmAccountStatus = LlmAccountStatus.ACTIVE,
    provider: str = "anthropic",
    model: str | None = "claude-opus-5-5",
    pct_5h: str | None = None,
    pct_week: str | None = None,
    resets_5h_in: float | None = None,
    resets_week_in: float | None = None,
    started_ago: float | None = None,
    rate_resets_in: float | None = None,
    turn_cost: str | None = None,
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
        usage_5h_resets_at=_at(resets_5h_in) if resets_5h_in is not None else None,
        usage_week_resets_at=_at(resets_week_in) if resets_week_in is not None else None,
        window_started_at=_at(-started_ago) if started_ago is not None else None,
        rate_limit_resets_at=_at(rate_resets_in) if rate_resets_in is not None else None,
        turn_cost_pct=Decimal(turn_cost) if turn_cost else None,
    )


def _choose(
    accounts: list[LlmAccount],
    *,
    current: LlmAccount | None = None,
    start: LlmAccount | None = None,
    tasks: dict[uuid.UUID, int] | None = None,
    now: datetime = _NOW,
    **request: Any,
) -> AccountChoice | LimitWait:
    load = tasks or {}
    if current is not None:
        load.setdefault(current.id, 1)
    views = [AccountView(account, tasks=load.get(account.id, 0)) for account in accounts]
    return choose_account(
        views,
        ChoiceRequest(
            now=now,
            threshold_pct=_THRESHOLD,
            current_id=current.id if current else None,
            start_id=start.id if start else None,
            **request,
        ),
    )


def _picked(choice: AccountChoice | LimitWait) -> tuple[LlmAccount, LlmSwitchReason]:
    assert isinstance(choice, AccountChoice)
    return choice.account, choice.reason


class TestLimitState:
    @pytest.mark.parametrize(
        ("fields", "running_turns", "plan_prompt", "expected"),
        [
            ({"status": LlmAccountStatus.LOGIN_REQUIRED}, 0, False, (LimitState.EXCLUDED, None)),
            ({"status": LlmAccountStatus.DISABLED}, 0, False, (LimitState.EXCLUDED, None)),
            ({"model": None}, 0, False, (LimitState.EXCLUDED, None)),
            ({"provider": "mistral"}, 0, False, (LimitState.EXCLUDED, None)),
            ({"provider": "google"}, 0, True, (LimitState.EXCLUDED, None)),
            (
                {"status": LlmAccountStatus.RATE_LIMITED, "rate_resets_in": 2},
                0,
                False,
                (LimitState.EXHAUSTED, _at(2)),
            ),
            (
                {"pct_week": "100", "resets_week_in": 30, "resets_5h_in": 1},
                0,
                False,
                (LimitState.EXHAUSTED, _at(30)),
            ),
            (
                {"pct_5h": "93", "resets_5h_in": 3},
                0,
                False,
                (LimitState.AT_THRESHOLD, _at(3)),
            ),
            ({"pct_5h": "93"}, 0, False, (LimitState.AT_THRESHOLD, _at(5))),
            (
                {"pct_5h": "92", "resets_5h_in": 3},
                1,
                False,
                (LimitState.AT_THRESHOLD, _at(3)),
            ),
            (
                {"pct_5h": "92", "resets_5h_in": 3, "turn_cost": "0.5"},
                1,
                False,
                (LimitState.RUNNING, _at(3)),
            ),
            ({"pct_5h": "92.99", "resets_5h_in": 3}, 0, False, (LimitState.RUNNING, _at(3))),
            ({"started_ago": 4}, 0, False, (LimitState.RUNNING, _at(1))),
            ({"started_ago": 5, "resets_5h_in": 0}, 0, False, (LimitState.FREE, None)),
            ({}, 0, False, (LimitState.FREE, None)),
            ({"provider": "google"}, 0, False, (LimitState.FREE, None)),
            ({"pct_5h": "95", "resets_5h_in": -0.5}, 0, False, (LimitState.FREE, None)),
            (
                {"status": LlmAccountStatus.RATE_LIMITED, "rate_resets_in": -0.1},
                0,
                False,
                (LimitState.FREE, None),
            ),
            ({"pct_week": "100", "resets_week_in": -1}, 0, False, (LimitState.FREE, None)),
        ],
        ids=[
            "login_required",
            "disabled",
            "no_model",
            "unknown_provider",
            "plan_unsupported",
            "rate_limited",
            "week_full",
            "at_threshold",
            "at_threshold_unknown_end",
            "reserve_default_cost",
            "reserve_own_cost",
            "below_threshold",
            "window_started",
            "window_reset",
            "no_data",
            "plan_not_needed",
            "usage_of_reset_window",
            "rate_limit_reset",
            "week_reset",
        ],
    )
    def test_state(
        self,
        fields: dict[str, Any],
        running_turns: int,
        plan_prompt: bool,
        expected: tuple[LimitState, datetime | None],
    ) -> None:
        view = AccountView(_account(1, **fields), running_turns=running_turns)

        limit = limit_state(view, threshold_pct=_THRESHOLD, now=_NOW, plan_prompt=plan_prompt)

        assert (limit.state, limit.until) == expected


class TestStart:
    def test_start_account(self) -> None:
        first, start = _account(1), _account(2)

        choice = _choose([first, start], start=start)

        assert _picked(choice) == (start, LlmSwitchReason.START)
        assert isinstance(choice, AccountChoice) and choice.opens_window

    def test_start_joins_running_window(self) -> None:
        running = _account(1, pct_5h="10", resets_5h_in=4)
        free = _account(2)

        choice = _choose([running, free], tasks_in_work=3)

        assert _picked(choice) == (running, LlmSwitchReason.START)
        assert isinstance(choice, AccountChoice) and not choice.opens_window

    @pytest.mark.parametrize(
        ("start_fields", "reason"),
        [
            ({"pct_5h": "93", "resets_5h_in": 1}, LlmSwitchReason.THRESHOLD_5H),
            ({"pct_week": "100"}, LlmSwitchReason.WEEK_EXHAUSTED),
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
        start, second = _account(1, **start_fields), _account(2)

        assert _picked(_choose([start, second], start=start)) == (second, reason)


class TestCurrentAccount:
    def test_kept_between_boundaries(self) -> None:
        current = _account(1, pct_5h="80", resets_5h_in=4)
        urgent = _account(2, pct_5h="0", resets_5h_in=0.5)

        choice = _choose([current, urgent], current=current, boundary=False, tasks_in_work=3)

        assert _picked(choice) == (current, LlmSwitchReason.KEPT)

    @pytest.mark.parametrize(
        ("current_fields", "plan_prompt", "reason"),
        [
            ({"pct_5h": "93.00", "resets_5h_in": 1}, False, LlmSwitchReason.THRESHOLD_5H),
            ({"pct_week": "100"}, False, LlmSwitchReason.WEEK_EXHAUSTED),
            ({"status": LlmAccountStatus.RATE_LIMITED}, False, LlmSwitchReason.RATE_LIMITED),
            ({"status": LlmAccountStatus.LOGIN_REQUIRED}, False, LlmSwitchReason.LOGIN_REQUIRED),
            ({"provider": "google"}, True, LlmSwitchReason.UNSUITABLE),
        ],
    )
    @pytest.mark.parametrize("boundary", [True, False])
    def test_left(
        self,
        current_fields: dict[str, Any],
        plan_prompt: bool,
        reason: LlmSwitchReason,
        boundary: bool,
    ) -> None:
        current = _account(1, **current_fields)
        other = _account(2, provider="openai", pct_5h="10", resets_5h_in=2)

        choice = _choose(
            [current, other],
            current=current,
            plan_prompt=plan_prompt,
            boundary=boundary,
        )

        assert _picked(choice) == (other, reason)

    def test_reset_window_reopened_by_current(self) -> None:
        other_free = _account(1)
        running = _account(2, pct_5h="10", resets_5h_in=2)
        current = _account(3, started_ago=6)

        choice = _choose([other_free, running, current], current=current, tasks_in_work=2)

        assert _picked(choice) == (current, LlmSwitchReason.KEPT)
        assert isinstance(choice, AccountChoice) and choice.opens_window


class TestPlannedWindow:
    @pytest.mark.parametrize(
        ("started_ago", "tasks_in_work", "opens"),
        [
            (2.5, 2, True),
            (2.49, 2, False),
            (2.5, 1, False),
            (4, 3, True),
        ],
        ids=["step_passed", "step_ahead", "windows_enough", "more_tasks"],
    )
    def test_opens_on_step(self, started_ago: float, tasks_in_work: int, opens: bool) -> None:
        current = _account(1, started_ago=started_ago)
        free = _account(2)

        choice = _choose([current, free], current=current, tasks_in_work=tasks_in_work)

        expected = (
            (free, LlmSwitchReason.WINDOW_PLANNED) if opens else (current, LlmSwitchReason.KEPT)
        )
        assert _picked(choice) == expected

    def test_not_opened_between_boundaries(self) -> None:
        current = _account(1, started_ago=4)
        free = _account(2)

        choice = _choose([current, free], current=current, tasks_in_work=2, boundary=False)

        assert _picked(choice) == (current, LlmSwitchReason.KEPT)

    def test_forced_switch_between_boundaries_joins_running(self) -> None:
        current = _account(1, pct_5h="93", resets_5h_in=2)
        running = _account(2, started_ago=4)
        free = _account(3)

        choice = _choose(
            [current, running, free],
            current=current,
            tasks_in_work=3,
            boundary=False,
        )

        assert _picked(choice) == (running, LlmSwitchReason.THRESHOLD_5H)

    def test_step_counts_latest_window(self) -> None:
        old = _account(1, started_ago=4)
        current = _account(2, started_ago=1)
        free = _account(3)

        choice = _choose([old, current, free], current=current, tasks_in_work=3)

        assert _picked(choice) == (current, LlmSwitchReason.KEPT)

    @pytest.mark.parametrize(
        ("candidates", "expected_order"),
        [
            (
                {
                    2: {"pct_week": "10", "resets_week_in": 100},
                    3: {"pct_week": "90", "resets_week_in": 3},
                },
                3,
            ),
            (
                {
                    2: {"pct_week": "50", "resets_week_in": 100},
                    3: {"pct_week": "20", "resets_week_in": 40},
                },
                3,
            ),
            ({2: {}, 3: {"pct_week": "99", "resets_week_in": 150}}, 3),
            ({2: {}, 3: {}}, 2),
        ],
        ids=["week_expiring", "week_pressure", "unknown_last", "switch_order"],
    )
    def test_free_account_order(
        self,
        candidates: dict[int, dict[str, Any]],
        expected_order: int,
    ) -> None:
        current = _account(1, started_ago=4)
        free = {order: _account(order, **fields) for order, fields in candidates.items()}

        choice = _choose([current, *free.values()], current=current, tasks_in_work=2)

        assert _picked(choice) == (free[expected_order], LlmSwitchReason.WINDOW_PLANNED)


class TestBalance:
    @pytest.mark.parametrize(
        ("other_fields", "other_tasks", "moves"),
        [
            ({"pct_5h": "20", "resets_5h_in": 1}, 0, True),
            ({"pct_5h": "80", "resets_5h_in": 1}, 0, False),
            ({"pct_5h": "20", "resets_5h_in": 1}, 5, False),
        ],
        ids=["more_urgent", "within_hysteresis", "crowded"],
    )
    def test_moves_to_urgent_window(
        self,
        other_fields: dict[str, Any],
        other_tasks: int,
        moves: bool,
    ) -> None:
        current = _account(1, pct_5h="50", resets_5h_in=4)
        other = _account(2, **other_fields)

        choice = _choose([current, other], current=current, tasks={other.id: other_tasks})

        expected = (
            (other, LlmSwitchReason.WINDOW_BALANCE) if moves else (current, LlmSwitchReason.KEPT)
        )
        assert _picked(choice) == expected

    def test_new_task_takes_urgent_window(self) -> None:
        relaxed = _account(1, pct_5h="10", resets_5h_in=4.5)
        urgent = _account(2, pct_5h="40", resets_5h_in=0.5)

        assert _picked(_choose([relaxed, urgent])) == (urgent, LlmSwitchReason.START)


class TestLimitWait:
    def test_waits_for_nearest_reset(self) -> None:
        accounts = [
            _account(1, pct_5h="95", resets_5h_in=3),
            _account(2, pct_week="100", resets_week_in=1.5),
            _account(3, status=LlmAccountStatus.LOGIN_REQUIRED),
        ]

        assert _choose(accounts, current=accounts[0]) == LimitWait(until=_at(1.5))

    def test_unknown_reset(self) -> None:
        account = _account(1, status=LlmAccountStatus.RATE_LIMITED)

        assert _choose([account]) == LimitWait(until=_at(5))

    def test_not_shorter_than_minute(self) -> None:
        account = _account(1, pct_5h="95", resets_5h_in=1 / 3600)

        assert _choose([account]) == LimitWait(until=_NOW + MIN_LIMIT_WAIT)

    @pytest.mark.parametrize(
        ("accounts", "plan_prompt"),
        [
            ([], False),
            ([_account(1, status=LlmAccountStatus.DISABLED)], False),
            ([_account(1, model=None), _account(2, provider="mistral")], False),
            ([_account(1, provider="xai")], True),
        ],
        ids=["none", "disabled", "unsuitable", "plan_prompt"],
    )
    def test_no_account(self, accounts: list[LlmAccount], plan_prompt: bool) -> None:
        with pytest.raises(NoLlmAccountAvailableError):
            _choose(accounts, plan_prompt=plan_prompt)


class TestWaitUntil:
    @pytest.mark.parametrize(
        ("accounts", "expected"),
        [
            ([_account(1, pct_5h="93", resets_5h_in=2)], _at(2)),
            ([_account(1, pct_5h="93", resets_5h_in=2), _account(2)], None),
            ([_account(1, status=LlmAccountStatus.DISABLED)], None),
        ],
        ids=["all_at_threshold", "free_left", "no_account"],
    )
    def test_gate(self, accounts: list[LlmAccount], expected: datetime | None) -> None:
        request = ChoiceRequest(now=_NOW, threshold_pct=_THRESHOLD, current_id=None, start_id=None)

        assert wait_until([AccountView(account) for account in accounts], request) == expected


class TestStaggeredWindows:
    """Пример ТЗ: три задачи в работе и четыре аккаунта — окна стартуют с шагом 5 ч / 4."""

    def test_three_tasks_four_accounts(self) -> None:
        accounts = [_account(order) for order in range(1, 5)]
        current: dict[str, LlmAccount] = {}
        timeline = [
            (0, "A"),
            (0, "B"),
            (0, "C"),
            (1.25, "A"),
            (1.5, "B"),
            (2.5, "B"),
            (3.75, "C"),
            (5, "C"),
        ]

        for hours, task in timeline:
            now = _at(hours)
            load: dict[uuid.UUID, int] = {}
            for account in current.values():
                load[account.id] = load.get(account.id, 0) + 1
            choice = _choose(
                accounts,
                current=current.get(task),
                tasks=load,
                now=now,
                tasks_in_work=3,
            )
            assert isinstance(choice, AccountChoice)
            if choice.opens_window:
                choice.account.window_started_at = now
            current[task] = choice.account

        starts = [account.window_started_at for account in accounts]
        assert starts == [_at(5), _at(1.25), _at(2.5), None]
        assert {task: account.label for task, account in current.items()} == {
            "A": "acc-2",
            "B": "acc-3",
            "C": "acc-1",
        }
