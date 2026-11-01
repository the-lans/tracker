"""Расход окон лимита LLM-аккаунта через прокси (раздел 19.7 ТЗ)."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import httpx
import pytest

from clients.cliproxy import CliproxyManagementClient, CliproxySettings
from db.models.enums import LlmAccountStatus
from db.models.llm import LlmAccount
from services import llm_usage
from services.llm_providers import UsageSource
from services.llm_usage import (
    UNKNOWN_RATE_LIMIT_WINDOW,
    UsageFormatError,
    UsageSnapshot,
    UsageWindow,
    apply_usage,
    parse_usage,
    refresh_account_usage,
)

_NOW = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
_RESET_5H = datetime(2026, 11, 1, 15, 0, tzinfo=UTC)
_RESET_WEEK = datetime(2026, 11, 5, 20, 0, tzinfo=UTC)
_UNKNOWN = UsageWindow(pct=None, resets_at=None)


def _anthropic(five_hour: Any, seven_day: Any) -> str:
    return json.dumps({"five_hour": five_hour, "seven_day": seven_day, "extra_usage": {}})


def _openai_window(pct: float, length: int, reset: datetime) -> dict[str, Any]:
    return {"used_percent": pct, "limit_window_seconds": length, "reset_at": int(reset.timestamp())}


def _openai(**windows: Any) -> str:
    return json.dumps({"plan_type": "plus", "rate_limit": {"allowed": True, **windows}})


class TestParseAnthropic:
    def test_windows(self) -> None:
        body = _anthropic(
            {"utilization": 55.0, "resets_at": _RESET_5H.isoformat()},
            {"utilization": 58.5, "resets_at": _RESET_WEEK.isoformat()},
        )

        assert parse_usage(UsageSource.ANTHROPIC_OAUTH, body) == UsageSnapshot(
            five_hour=UsageWindow(Decimal("55.00"), _RESET_5H),
            week=UsageWindow(Decimal("58.50"), _RESET_WEEK),
        )

    def test_null_window_is_unknown(self) -> None:
        body = _anthropic(None, {"utilization": 3, "resets_at": None})

        snapshot = parse_usage(UsageSource.ANTHROPIC_OAUTH, body)

        assert snapshot == UsageSnapshot(_UNKNOWN, UsageWindow(Decimal("3.00"), None))

    @pytest.mark.parametrize(
        ("utilization", "expected"),
        [(-5, Decimal("0.00")), (100.4, Decimal("100.00")), ("12.345", Decimal("12.34"))],
    )
    def test_pct_clamped_and_rounded(self, utilization: Any, expected: Decimal) -> None:
        body = _anthropic({"utilization": utilization, "resets_at": None}, None)

        assert parse_usage(UsageSource.ANTHROPIC_OAUTH, body).five_hour.pct == expected


class TestParseOpenai:
    def test_windows_by_length(self) -> None:
        body = _openai(
            primary_window=_openai_window(4, 18000, _RESET_5H),
            secondary_window=_openai_window(42, 604800, _RESET_WEEK),
        )

        assert parse_usage(UsageSource.OPENAI_WHAM, body) == UsageSnapshot(
            five_hour=UsageWindow(Decimal("4.00"), _RESET_5H),
            week=UsageWindow(Decimal("42.00"), _RESET_WEEK),
        )

    def test_swapped_windows(self) -> None:
        body = _openai(
            primary_window=_openai_window(42, 604800, _RESET_WEEK),
            secondary_window=_openai_window(4, 18000, _RESET_5H),
        )

        snapshot = parse_usage(UsageSource.OPENAI_WHAM, body)

        assert (snapshot.five_hour.pct, snapshot.week.pct) == (Decimal("4.00"), Decimal("42.00"))

    def test_missing_week_is_unknown(self) -> None:
        body = _openai(primary_window=_openai_window(7, 18000, _RESET_5H), secondary_window=None)

        assert parse_usage(UsageSource.OPENAI_WHAM, body).week == _UNKNOWN


class TestFormatErrors:
    @pytest.mark.parametrize(
        ("source", "body"),
        [
            (UsageSource.ANTHROPIC_OAUTH, "not json"),
            (UsageSource.ANTHROPIC_OAUTH, "[]"),
            (UsageSource.ANTHROPIC_OAUTH, json.dumps({"five_hour": {}})),
            (UsageSource.ANTHROPIC_OAUTH, _anthropic({"utilization": "много"}, None)),
            (UsageSource.ANTHROPIC_OAUTH, _anthropic({"utilization": 1, "resets_at": "x"}, None)),
            (UsageSource.ANTHROPIC_OAUTH, _anthropic("55%", None)),
            (UsageSource.OPENAI_WHAM, json.dumps({"rate_limit": None})),
            (UsageSource.OPENAI_WHAM, _openai(primary_window=None, secondary_window=None)),
            (UsageSource.OPENAI_WHAM, _openai(primary_window={"used_percent": 1, "reset_at": "x"})),
            (UsageSource.OPENAI_WHAM, _openai(primary_window={"used_percent": True})),
        ],
    )
    def test_rejected(self, source: UsageSource, body: str) -> None:
        with pytest.raises(UsageFormatError):
            parse_usage(source, body)


def _account(
    status: LlmAccountStatus = LlmAccountStatus.ACTIVE,
    provider: str = "anthropic",
) -> LlmAccount:
    return LlmAccount(id=uuid.uuid4(), label="main", provider=provider, status=status)


def _snapshot(pct_5h: str | None, pct_week: str | None) -> UsageSnapshot:
    return UsageSnapshot(
        five_hour=UsageWindow(Decimal(pct_5h) if pct_5h else None, _RESET_5H),
        week=UsageWindow(Decimal(pct_week) if pct_week else None, _RESET_WEEK),
    )


class TestApplyUsage:
    def test_saves_windows(self) -> None:
        account = _account()

        apply_usage(account, _snapshot("12.50", "40"), now=_NOW)

        assert account.usage_5h_pct == Decimal("12.50")
        assert account.usage_week_pct == Decimal("40")
        assert account.usage_5h_resets_at == _RESET_5H
        assert account.usage_week_resets_at == _RESET_WEEK
        assert (account.usage_checked_at, account.status) == (_NOW, LlmAccountStatus.ACTIVE)

    @pytest.mark.parametrize(
        ("pct_5h", "pct_week", "resets_at"),
        [("100", "40", _RESET_5H), ("30", "100", _RESET_WEEK), ("100", "100", _RESET_WEEK)],
    )
    def test_exhausted_window_rate_limits(
        self,
        pct_5h: str,
        pct_week: str,
        resets_at: datetime,
    ) -> None:
        account = _account()

        apply_usage(account, _snapshot(pct_5h, pct_week), now=_NOW)

        assert (account.status, account.rate_limit_resets_at) == (
            LlmAccountStatus.RATE_LIMITED,
            resets_at,
        )

    def test_unknown_reset_waits_an_hour(self) -> None:
        account = _account()
        snapshot = UsageSnapshot(
            five_hour=UsageWindow(Decimal(100), None),
            week=UsageWindow(None, None),
        )

        apply_usage(account, snapshot, now=_NOW)

        assert (account.status, account.rate_limit_resets_at) == (
            LlmAccountStatus.RATE_LIMITED,
            _NOW + UNKNOWN_RATE_LIMIT_WINDOW,
        )

    @pytest.mark.parametrize(
        "status",
        [LlmAccountStatus.DISABLED, LlmAccountStatus.LOGIN_REQUIRED, LlmAccountStatus.RATE_LIMITED],
    )
    def test_only_active_rate_limited(self, status: LlmAccountStatus) -> None:
        account = _account(status)

        apply_usage(account, _snapshot("100", None), now=_NOW)

        assert (account.status, account.rate_limit_resets_at) == (status, None)


def _cliproxy(reply: httpx.Response, calls: list[dict[str, Any]]) -> CliproxyManagementClient:
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content))
        return reply

    return CliproxyManagementClient(
        settings=CliproxySettings(url="http://cliproxy:8317", management_key="key"),
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


@pytest.fixture
def app_logs(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    written: list[dict[str, Any]] = []

    async def record(**kwargs: Any) -> None:
        written.append(kwargs)

    monkeypatch.setattr(llm_usage, "write_app_log", record)
    return written


class TestRefreshAccountUsage:
    async def test_polls_through_proxy(self, app_logs: list[dict[str, Any]]) -> None:
        body = _anthropic({"utilization": 20}, {"utilization": 30})
        calls: list[dict[str, Any]] = []
        account = _account()

        snapshot = await refresh_account_usage(
            _cliproxy(httpx.Response(200, json={"status_code": 200, "body": body}), calls),
            account,
            auth_index="idx-1",
            now=_NOW,
        )

        assert snapshot is not None
        assert (account.usage_5h_pct, account.usage_week_pct) == (Decimal(20), Decimal(30))
        assert calls == [
            {
                "auth_index": "idx-1",
                "method": "GET",
                "url": "https://api.anthropic.com/api/oauth/usage",
                "header": {"Authorization": "Bearer $TOKEN$", "anthropic-beta": "oauth-2025-04-20"},
            },
        ]
        assert app_logs == []

    @pytest.mark.parametrize(
        "reply",
        [
            httpx.Response(200, json={"status_code": 401, "body": "{}"}),
            httpx.Response(200, json={"status_code": 200, "body": "<html>"}),
            httpx.Response(503, text="down"),
        ],
    )
    async def test_failure_keeps_values(
        self,
        reply: httpx.Response,
        app_logs: list[dict[str, Any]],
    ) -> None:
        account = _account()
        account.usage_5h_pct = Decimal("10")

        snapshot = await refresh_account_usage(
            _cliproxy(reply, []),
            account,
            auth_index="idx-1",
            now=_NOW,
        )

        assert snapshot is None
        assert (account.usage_5h_pct, account.usage_checked_at) == (Decimal("10"), None)
        assert [entry["source"] for entry in app_logs] == ["llm_usage"]

    async def test_provider_without_usage(self, app_logs: list[dict[str, Any]]) -> None:
        calls: list[dict[str, Any]] = []

        snapshot = await refresh_account_usage(
            _cliproxy(httpx.Response(500), calls),
            _account(provider="google"),
            auth_index="idx-1",
            now=_NOW,
        )

        assert (snapshot, calls, app_logs) == (None, [], [])
