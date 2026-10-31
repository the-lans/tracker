"""Вход в LLM-аккаунт через прокси (раздел 19.5 ТЗ)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from clients.cliproxy import OAuthState
from db.models.enums import LlmAccountStatus
from db.models.llm import LlmAccount
from services.errors import ConflictError, ValidationError
from services.llm_account_login import (
    LOGIN_TIMEOUT,
    LoginResult,
    cancel_expired_logins,
    cancel_login,
    poll_login,
    start_login,
    submit_login_callback,
)
from tests.cliproxy_support import FakeCliproxy, NextLogin
from tests.factories import make_llm_account, make_user

if TYPE_CHECKING:
    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncSession

_NOW = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
_REDIRECT = "http://localhost:54545/callback?code=abc&state=x"
_CLAUDE = "claude-owner@example.com.json"
_CODEX = "codex-owner@example.com.json"


async def _account(
    db_session: AsyncSession,
    *,
    provider: str = "anthropic",
    credential: str | None = None,
    status: LlmAccountStatus = LlmAccountStatus.LOGIN_REQUIRED,
) -> LlmAccount:
    owner = await make_user(db_session)
    return await make_llm_account(
        db_session,
        owner_id=owner.id,
        provider=provider,
        credential=credential,
        status=status,
    )


async def _sign_in(
    db_session: AsyncSession,
    redis_client: Redis,
    fake_cliproxy: FakeCliproxy,
    account: LlmAccount,
) -> LoginResult:
    cliproxy = fake_cliproxy.client()
    await start_login(redis_client, cliproxy, account, now=_NOW)
    return await submit_login_callback(
        db_session,
        redis_client,
        cliproxy,
        account,
        redirect_url=_REDIRECT,
        now=_NOW,
    )


class TestStartLogin:
    @pytest.mark.parametrize(
        ("provider", "oauth_provider"),
        [("anthropic", "claude"), ("openai", "codex"), ("google", "antigravity")],
    )
    async def test_link_for_provider(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        fake_cliproxy: FakeCliproxy,
        provider: str,
        oauth_provider: str,
    ) -> None:
        account = await _account(db_session, provider=provider)

        start = await start_login(redis_client, fake_cliproxy.client(), account, now=_NOW)

        assert start.url == f"https://auth.example.com/{start.state}"
        assert fake_cliproxy.sessions[start.state].provider == oauth_provider
        assert fake_cliproxy.sessions[start.state].target is None

    async def test_relogin_targets_own_credential(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        fake_cliproxy: FakeCliproxy,
    ) -> None:
        fake_cliproxy.add_credential(_CLAUDE)
        account = await _account(db_session, credential=_CLAUDE)

        start = await start_login(redis_client, fake_cliproxy.client(), account, now=_NOW)

        assert fake_cliproxy.sessions[start.state].target == _CLAUDE

    async def test_restart_cancels_previous(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        fake_cliproxy: FakeCliproxy,
    ) -> None:
        account = await _account(db_session)
        cliproxy = fake_cliproxy.client()
        first = await start_login(redis_client, cliproxy, account, now=_NOW)

        second = await start_login(redis_client, cliproxy, account, now=_NOW)

        assert fake_cliproxy.cancelled == [first.state]
        assert set(fake_cliproxy.sessions) == {second.state}


class TestBinding:
    @pytest.mark.parametrize(
        ("provider", "oauth_provider", "name", "returns_auth_id"),
        [
            ("anthropic", "claude", _CLAUDE, False),
            ("openai", "codex", _CODEX, True),
        ],
        ids=["diff_of_credentials", "auth_id_from_status"],
    )
    async def test_new_credential_bound_with_prefix(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        fake_cliproxy: FakeCliproxy,
        provider: str,
        oauth_provider: str,
        name: str,
        returns_auth_id: bool,
    ) -> None:
        fake_cliproxy.add_credential("other-user@example.com.json", provider=oauth_provider)
        fake_cliproxy.next_login = NextLogin(name=name, returns_auth_id=returns_auth_id)
        account = await _account(db_session, provider=provider)

        result = await _sign_in(db_session, redis_client, fake_cliproxy, account)

        assert result == LoginResult(OAuthState.OK)
        assert (account.cliproxy_credential, account.status) == (name, LlmAccountStatus.ACTIVE)
        assert fake_cliproxy.credentials[name].prefix == account.cliproxy_prefix

    async def test_relogin_keeps_credential(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        fake_cliproxy: FakeCliproxy,
    ) -> None:
        fake_cliproxy.add_credential(_CLAUDE)
        account = await _account(db_session, credential=_CLAUDE)

        result = await _sign_in(db_session, redis_client, fake_cliproxy, account)

        assert result.state is OAuthState.OK
        assert (account.cliproxy_credential, account.status) == (_CLAUDE, LlmAccountStatus.ACTIVE)

    async def test_disabled_account_stays_disabled(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        fake_cliproxy: FakeCliproxy,
    ) -> None:
        fake_cliproxy.add_credential(_CLAUDE)
        account = await _account(db_session, credential=_CLAUDE, status=LlmAccountStatus.DISABLED)

        await _sign_in(db_session, redis_client, fake_cliproxy, account)

        assert account.status is LlmAccountStatus.DISABLED

    async def test_subscription_of_other_account_conflicts(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        fake_cliproxy: FakeCliproxy,
    ) -> None:
        fake_cliproxy.add_credential(_CODEX, provider="codex")
        await _account(db_session, provider="openai", credential=_CODEX)
        fake_cliproxy.next_login = NextLogin(name=_CODEX, returns_auth_id=True)
        account = await _account(db_session, provider="openai")

        with pytest.raises(ConflictError):
            await _sign_in(db_session, redis_client, fake_cliproxy, account)

        assert account.cliproxy_credential is None
        assert fake_cliproxy.credentials[_CODEX].prefix is None

    async def test_no_new_credential_conflicts(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        fake_cliproxy: FakeCliproxy,
    ) -> None:
        fake_cliproxy.add_credential(_CLAUDE)
        await _account(db_session, credential=_CLAUDE)
        fake_cliproxy.next_login = NextLogin(name=_CLAUDE, returns_auth_id=False)
        account = await _account(db_session)

        with pytest.raises(ConflictError):
            await _sign_in(db_session, redis_client, fake_cliproxy, account)

    async def test_two_new_credentials_conflict(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        fake_cliproxy: FakeCliproxy,
    ) -> None:
        account = await _account(db_session)
        cliproxy = fake_cliproxy.client()
        await start_login(redis_client, cliproxy, account, now=_NOW)
        fake_cliproxy.add_credential("claude-parallel@example.com.json")
        fake_cliproxy.next_login = NextLogin(name=_CLAUDE, returns_auth_id=False)

        with pytest.raises(ConflictError):
            await submit_login_callback(
                db_session,
                redis_client,
                cliproxy,
                account,
                redirect_url=_REDIRECT,
                now=_NOW,
            )

    async def test_busy_binding_conflicts(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        fake_cliproxy: FakeCliproxy,
    ) -> None:
        fake_cliproxy.next_login = NextLogin(name=_CLAUDE, returns_auth_id=False)
        account = await _account(db_session)
        await redis_client.set("lock:cliproxy:login", "other", ex=30)

        with pytest.raises(ConflictError):
            await _sign_in(db_session, redis_client, fake_cliproxy, account)

        assert account.cliproxy_credential is None


class TestLoginProgress:
    async def test_wait_until_callback(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        fake_cliproxy: FakeCliproxy,
    ) -> None:
        account = await _account(db_session)
        cliproxy = fake_cliproxy.client()
        await start_login(redis_client, cliproxy, account, now=_NOW)

        result = await poll_login(db_session, redis_client, cliproxy, account, now=_NOW)

        assert result == LoginResult(OAuthState.WAIT)

    async def test_provider_error(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        fake_cliproxy: FakeCliproxy,
    ) -> None:
        fake_cliproxy.next_login = NextLogin(name=_CLAUDE, returns_auth_id=False, error="denied")
        account = await _account(db_session)

        result = await _sign_in(db_session, redis_client, fake_cliproxy, account)

        assert result == LoginResult(OAuthState.ERROR, "denied")
        assert account.status is LlmAccountStatus.LOGIN_REQUIRED
        cliproxy = fake_cliproxy.client()
        again = await poll_login(db_session, redis_client, cliproxy, account, now=_NOW)
        assert again.state is OAuthState.ERROR

    @pytest.mark.parametrize("started", [False, True], ids=["not_started", "expired"])
    async def test_expired_or_missing(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        fake_cliproxy: FakeCliproxy,
        started: bool,
    ) -> None:
        account = await _account(db_session)
        cliproxy = fake_cliproxy.client()
        if started:
            await start_login(redis_client, cliproxy, account, now=_NOW)

        result = await submit_login_callback(
            db_session,
            redis_client,
            cliproxy,
            account,
            redirect_url=_REDIRECT,
            now=_NOW + LOGIN_TIMEOUT,
        )

        assert result.state is OAuthState.ERROR
        assert len(fake_cliproxy.cancelled) == int(started)
        assert ("POST", "/oauth/callback") not in fake_cliproxy.requests


class TestCancel:
    async def test_cancel_login(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        fake_cliproxy: FakeCliproxy,
    ) -> None:
        account = await _account(db_session)
        cliproxy = fake_cliproxy.client()
        start = await start_login(redis_client, cliproxy, account, now=_NOW)

        await cancel_login(redis_client, cliproxy, account)
        await cancel_login(redis_client, cliproxy, account)

        assert fake_cliproxy.cancelled == [start.state]

    async def test_cancel_expired_logins(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        fake_cliproxy: FakeCliproxy,
    ) -> None:
        cliproxy = fake_cliproxy.client()
        old = await _account(db_session)
        fresh = await _account(db_session)
        old_start = await start_login(redis_client, cliproxy, old, now=_NOW)
        await start_login(redis_client, cliproxy, fresh, now=_NOW + timedelta(minutes=5))

        cancelled = await cancel_expired_logins(redis_client, cliproxy, now=_NOW + LOGIN_TIMEOUT)

        assert (cancelled, fake_cliproxy.cancelled) == (1, [old_start.state])
        assert (await poll_login(db_session, redis_client, cliproxy, fresh, now=_NOW)).state is (
            OAuthState.WAIT
        )

    async def test_unknown_provider(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        fake_cliproxy: FakeCliproxy,
    ) -> None:
        account = await _account(db_session)
        account.provider = "mistral"

        with pytest.raises(ValidationError):
            await start_login(redis_client, fake_cliproxy.client(), account, now=_NOW)
