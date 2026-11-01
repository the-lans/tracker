"""Периодическая сверка LLM-аккаунтов с прокси (разделы 16.2, 19.5, 19.7 ТЗ)."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import pytest

from db.models.enums import LlmAccountStatus
from db.models.llm import LlmAccount
from services.llm_account_checks import check_llm_accounts, require_login
from services.llm_account_login import start_login
from services.notifications import NotificationEvent
from tests.cliproxy_support import FakeCliproxy
from tests.factories import make_llm_account, make_user

if TYPE_CHECKING:
    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncSession

_NOW = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
_ANTHROPIC_USAGE = "https://api.anthropic.com/api/oauth/usage"
_OPENAI_USAGE = "https://chatgpt.com/backend-api/wham/usage"
_NEW_CREDENTIAL = "new-owner@example.com.json"


@pytest.fixture
def pushes(monkeypatch: pytest.MonkeyPatch) -> list[tuple[NotificationEvent, uuid.UUID]]:
    sent: list[tuple[NotificationEvent, uuid.UUID]] = []

    async def record(
        _db: AsyncSession,
        *,
        event: NotificationEvent,
        user_id: uuid.UUID,
        **_: Any,
    ) -> None:
        sent.append((event, user_id))

    async def no_app_log(**_: Any) -> None:
        return None

    monkeypatch.setattr("services.llm_account_checks.notify_user_event", record)
    monkeypatch.setattr("services.llm_usage.write_app_log", no_app_log)
    return sent


async def _account(
    db_session: AsyncSession,
    fake_cliproxy: FakeCliproxy,
    *,
    provider: str = "anthropic",
    status: LlmAccountStatus = LlmAccountStatus.ACTIVE,
    in_proxy: bool = True,
) -> LlmAccount:
    owner = await make_user(db_session)
    credential = f"{uuid.uuid4().hex}@example.com.json"
    account = await make_llm_account(
        db_session,
        owner_id=owner.id,
        provider=provider,
        credential=credential,
        status=status,
    )
    if in_proxy:
        fake_cliproxy.add_credential(credential)
    return account


async def _check(
    db_session: AsyncSession,
    redis_client: Redis,
    fake_cliproxy: FakeCliproxy,
    *,
    now: datetime = _NOW,
) -> Any:
    return await check_llm_accounts(
        db_session,
        redis_client=redis_client,
        cliproxy=fake_cliproxy.client(),
        now=now,
    )


def _anthropic_usage(pct: float) -> tuple[int, str]:
    return 200, json.dumps({"five_hour": {"utilization": pct}, "seven_day": None})


@pytest.mark.usefixtures("pushes")
class TestUsage:
    @pytest.mark.parametrize(
        "status",
        [LlmAccountStatus.ACTIVE, LlmAccountStatus.RATE_LIMITED],
    )
    async def test_signed_in_polled(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        fake_cliproxy: FakeCliproxy,
        status: LlmAccountStatus,
    ) -> None:
        fake_cliproxy.api_responses[_ANTHROPIC_USAGE] = _anthropic_usage(42)
        account = await _account(db_session, fake_cliproxy, status=status)
        account.rate_limit_resets_at = _NOW + timedelta(hours=1)
        await db_session.flush()

        result = await _check(db_session, redis_client, fake_cliproxy)

        await db_session.refresh(account)
        assert result.polled == [account.id]
        assert (account.usage_5h_pct, account.usage_checked_at) == (Decimal("42.00"), _NOW)

    @pytest.mark.parametrize(
        "status",
        [LlmAccountStatus.DISABLED, LlmAccountStatus.LOGIN_REQUIRED],
    )
    async def test_without_sign_in_skipped(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        fake_cliproxy: FakeCliproxy,
        status: LlmAccountStatus,
    ) -> None:
        await _account(db_session, fake_cliproxy, status=status)

        result = await _check(db_session, redis_client, fake_cliproxy)

        assert (result.polled, fake_cliproxy.api_calls) == ([], [])

    async def test_one_failure_does_not_stop_others(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        fake_cliproxy: FakeCliproxy,
    ) -> None:
        fake_cliproxy.api_responses[_ANTHROPIC_USAGE] = (401, "{}")
        fake_cliproxy.api_responses[_OPENAI_USAGE] = (
            200,
            json.dumps({"rate_limit": {"primary_window": {"used_percent": 7}}}),
        )
        await _account(db_session, fake_cliproxy)
        codex = await _account(db_session, fake_cliproxy, provider="openai")

        result = await _check(db_session, redis_client, fake_cliproxy)

        assert result.polled == [codex.id]

    async def test_expired_rate_limit_restored(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        fake_cliproxy: FakeCliproxy,
    ) -> None:
        account = await _account(db_session, fake_cliproxy, status=LlmAccountStatus.RATE_LIMITED)
        account.rate_limit_resets_at = _NOW - timedelta(minutes=1)
        await db_session.flush()

        result = await _check(db_session, redis_client, fake_cliproxy)

        await db_session.refresh(account)
        assert (result.restored, account.status) == ([account.id], LlmAccountStatus.ACTIVE)


class TestSignIn:
    @pytest.mark.parametrize("in_proxy", [True, False], ids=["requires_sign_in", "gone"])
    async def test_login_required_pushed_once(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        fake_cliproxy: FakeCliproxy,
        pushes: list[tuple[NotificationEvent, uuid.UUID]],
        in_proxy: bool,
    ) -> None:
        account = await _account(db_session, fake_cliproxy, in_proxy=in_proxy)
        if in_proxy:
            fake_cliproxy.credentials[str(account.cliproxy_credential)].requires_sign_in = True

        first = await _check(db_session, redis_client, fake_cliproxy)
        second = await _check(db_session, redis_client, fake_cliproxy)

        await db_session.refresh(account)
        assert account.status is LlmAccountStatus.LOGIN_REQUIRED
        assert (first.login_required, second.login_required) == ([account.id], [])
        assert pushes == [(NotificationEvent.LLM_LOGIN_REQUIRED, account.created_by)]
        assert fake_cliproxy.api_calls == []


    async def test_login_finished_during_check_kept(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        fake_cliproxy: FakeCliproxy,
        pushes: list[tuple[NotificationEvent, uuid.UUID]],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        owner = await make_user(db_session)
        account = await make_llm_account(
            db_session,
            owner_id=owner.id,
            status=LlmAccountStatus.LOGIN_REQUIRED,
        )
        cliproxy = fake_cliproxy.client()
        list_credentials = cliproxy.list_credentials

        async def listed_then_signed_in() -> Any:
            # Прокси уже отдал список, а вход аккаунта завершился сразу после.
            credentials = await list_credentials()
            account.status, account.cliproxy_credential = LlmAccountStatus.ACTIVE, _NEW_CREDENTIAL
            await db_session.commit()
            fake_cliproxy.add_credential(_NEW_CREDENTIAL)
            return credentials

        monkeypatch.setattr(cliproxy, "list_credentials", listed_then_signed_in)

        result = await check_llm_accounts(
            db_session,
            redis_client=redis_client,
            cliproxy=cliproxy,
            now=_NOW,
        )

        await db_session.refresh(account)
        assert (account.status, result.login_required, pushes) == (LlmAccountStatus.ACTIVE, [], [])


@pytest.mark.usefixtures("pushes")
class TestProxy:
    async def test_down_only_restores(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        fake_cliproxy: FakeCliproxy,
    ) -> None:
        account = await _account(db_session, fake_cliproxy, status=LlmAccountStatus.RATE_LIMITED)
        account.rate_limit_resets_at = _NOW - timedelta(minutes=1)
        await db_session.flush()
        fake_cliproxy.down = True

        result = await _check(db_session, redis_client, fake_cliproxy)

        assert (result.restored, result.polled, result.login_required) == ([account.id], [], [])

    async def test_expired_logins_cancelled(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        fake_cliproxy: FakeCliproxy,
    ) -> None:
        owner = await make_user(db_session)
        pending = await make_llm_account(
            db_session,
            owner_id=owner.id,
            status=LlmAccountStatus.LOGIN_REQUIRED,
        )
        start = await start_login(redis_client, fake_cliproxy.client(), pending, now=_NOW)

        later = _NOW + timedelta(hours=1)

        result = await _check(db_session, redis_client, fake_cliproxy, now=later)

        assert (result.cancelled_logins, fake_cliproxy.cancelled) == (1, [start.state])


class TestRequireLogin:
    @pytest.mark.parametrize(
        ("status", "changed"),
        [
            (LlmAccountStatus.ACTIVE, True),
            (LlmAccountStatus.RATE_LIMITED, True),
            (LlmAccountStatus.LOGIN_REQUIRED, False),
            (LlmAccountStatus.DISABLED, False),
        ],
    )
    async def test_compare_and_swap(
        self,
        db_session: AsyncSession,
        fake_cliproxy: FakeCliproxy,
        pushes: list[tuple[NotificationEvent, uuid.UUID]],
        status: LlmAccountStatus,
        changed: bool,
    ) -> None:
        account = await _account(db_session, fake_cliproxy, status=status)

        assert await require_login(db_session, account.id) is changed

        assert len(pushes) == int(changed)
