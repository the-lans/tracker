"""Тесты `services/llm_accounts.py` (разделы 3.2, 15.1, 16.2, 19.5 ТЗ)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from clients.cliproxy import CliproxyUnavailableError
from db.models.enums import LlmAccountStatus, NodeLogTriggerType
from db.models.llm import LlmAccount
from db.models.logs import NodeLog
from services.errors import ConflictError, ValidationError
from services.llm_accounts import (
    account_models,
    create_account,
    delete_account,
    ensure_model_available,
    owned_accounts,
    reorder_accounts,
    restore_expired_rate_limits,
    set_account_enabled,
)
from tests.cliproxy_support import FakeCliproxy
from tests.factories import make_llm_account, make_task, make_user

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession



async def _account(db_session: AsyncSession, status: LlmAccountStatus) -> LlmAccount:
    owner = await make_user(db_session)
    return await make_llm_account(db_session, owner_id=owner.id, status=status)


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


_CREDENTIAL = "claude-owner@example.com.json"
_NOW = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)


async def _signed_in(
    db_session: AsyncSession,
    fake_cliproxy: FakeCliproxy,
    *,
    status: LlmAccountStatus = LlmAccountStatus.ACTIVE,
) -> LlmAccount:
    owner = await make_user(db_session)
    account = await make_llm_account(
        db_session,
        owner_id=owner.id,
        credential=_CREDENTIAL,
        status=status,
    )
    credential = fake_cliproxy.add_credential(_CREDENTIAL, models=["claude-opus-5-5", "claude-x"])
    credential.prefix = account.cliproxy_prefix
    await db_session.commit()
    return account


class TestCreateAccount:
    async def test_appended_to_order(self, db_session: AsyncSession) -> None:
        owner = await make_user(db_session)
        first = await create_account(db_session, owner_id=owner.id, label="a", provider="anthropic")
        second = await create_account(db_session, owner_id=owner.id, label="b", provider="openai")

        assert [(a.switch_order, a.provider) for a in (first, second)] == [
            (1, "anthropic"),
            (2, "openai"),
        ]
        assert second.status is LlmAccountStatus.LOGIN_REQUIRED
        assert second.cliproxy_prefix == f"acc-{second.id.hex[:12]}"

    async def test_unknown_provider(self, db_session: AsyncSession) -> None:
        owner = await make_user(db_session)

        with pytest.raises(ValidationError):
            await create_account(db_session, owner_id=owner.id, label="a", provider="mistral")


class TestModels:
    async def test_without_prefix(
        self,
        db_session: AsyncSession,
        fake_cliproxy: FakeCliproxy,
    ) -> None:
        account = await _signed_in(db_session, fake_cliproxy)

        models = await account_models(fake_cliproxy.client(), account)

        assert models == ["claude-opus-5-5", "claude-x"]

    async def test_empty_before_login(
        self,
        db_session: AsyncSession,
        fake_cliproxy: FakeCliproxy,
    ) -> None:
        owner = await make_user(db_session)
        account = await make_llm_account(db_session, owner_id=owner.id)

        assert await account_models(fake_cliproxy.client(), account) == []
        with pytest.raises(ValidationError):
            await ensure_model_available(fake_cliproxy.client(), account, "claude-opus-5-5")

    @pytest.mark.parametrize(("model", "allowed"), [("claude-x", True), ("gpt-6-sol", False)])
    async def test_model_must_be_listed(
        self,
        db_session: AsyncSession,
        fake_cliproxy: FakeCliproxy,
        model: str,
        allowed: bool,
    ) -> None:
        account = await _signed_in(db_session, fake_cliproxy)

        if allowed:
            await ensure_model_available(fake_cliproxy.client(), account, model)
        else:
            with pytest.raises(ValidationError):
                await ensure_model_available(fake_cliproxy.client(), account, model)


class TestReorder:
    async def test_new_order(self, db_session: AsyncSession) -> None:
        owner = await make_user(db_session)
        first, second, third = [
            await make_llm_account(db_session, owner_id=owner.id) for _ in range(3)
        ]

        await reorder_accounts(
            db_session,
            owner_id=owner.id,
            account_ids=[third.id, first.id, second.id],
        )

        assert [a.id for a in await owned_accounts(db_session, owner.id)] == [
            third.id,
            first.id,
            second.id,
        ]

    @pytest.mark.parametrize("variant", ["missing", "duplicate", "foreign"])
    async def test_must_list_each_once(self, db_session: AsyncSession, variant: str) -> None:
        owner = await make_user(db_session)
        first = await make_llm_account(db_session, owner_id=owner.id)
        second = await make_llm_account(db_session, owner_id=owner.id)
        ids = {
            "missing": [first.id],
            "duplicate": [first.id, first.id, second.id],
            "foreign": [first.id, second.id, uuid.uuid4()],
        }[variant]

        with pytest.raises(ValidationError):
            await reorder_accounts(db_session, owner_id=owner.id, account_ids=ids)


class TestSetEnabled:
    async def test_disable_in_proxy_too(
        self,
        db_session: AsyncSession,
        fake_cliproxy: FakeCliproxy,
    ) -> None:
        account = await _signed_in(db_session, fake_cliproxy)

        await set_account_enabled(
            db_session,
            fake_cliproxy.client(),
            account,
            enabled=False,
            now=_NOW,
        )

        assert account.status is LlmAccountStatus.DISABLED
        assert fake_cliproxy.credentials[_CREDENTIAL].disabled is True

    @pytest.mark.parametrize(
        ("credential", "resets_at", "expected"),
        [
            (_CREDENTIAL, None, LlmAccountStatus.ACTIVE),
            (_CREDENTIAL, _NOW + timedelta(hours=1), LlmAccountStatus.RATE_LIMITED),
            (_CREDENTIAL, _NOW - timedelta(hours=1), LlmAccountStatus.ACTIVE),
            (None, None, LlmAccountStatus.LOGIN_REQUIRED),
        ],
    )
    async def test_enable_restores_status(
        self,
        db_session: AsyncSession,
        fake_cliproxy: FakeCliproxy,
        credential: str | None,
        resets_at: datetime | None,
        expected: LlmAccountStatus,
    ) -> None:
        account = await _signed_in(db_session, fake_cliproxy, status=LlmAccountStatus.DISABLED)
        fake_cliproxy.credentials[_CREDENTIAL].disabled = True
        account.cliproxy_credential = credential
        account.rate_limit_resets_at = resets_at

        await set_account_enabled(
            db_session,
            fake_cliproxy.client(),
            account,
            enabled=True,
            now=_NOW,
        )

        assert account.status is expected
        assert fake_cliproxy.credentials[_CREDENTIAL].disabled is (credential is None)

    async def test_proxy_down_keeps_status(
        self,
        db_session: AsyncSession,
        fake_cliproxy: FakeCliproxy,
    ) -> None:
        account = await _signed_in(db_session, fake_cliproxy)
        fake_cliproxy.down = True

        with pytest.raises(CliproxyUnavailableError):
            await set_account_enabled(
                db_session,
                fake_cliproxy.client(),
                account,
                enabled=False,
                now=_NOW,
            )

        assert account.status is LlmAccountStatus.ACTIVE


class TestDeleteAccount:
    async def test_removes_credential(
        self,
        db_session: AsyncSession,
        fake_cliproxy: FakeCliproxy,
    ) -> None:
        account = await _signed_in(db_session, fake_cliproxy)

        await delete_account(db_session, fake_cliproxy.client(), account)

        assert await db_session.get(LlmAccount, account.id) is None
        assert fake_cliproxy.credentials == {}

    async def test_credential_already_gone(
        self,
        db_session: AsyncSession,
        fake_cliproxy: FakeCliproxy,
    ) -> None:
        account = await _signed_in(db_session, fake_cliproxy)
        fake_cliproxy.credentials.clear()

        await delete_account(db_session, fake_cliproxy.client(), account)

        assert await db_session.get(LlmAccount, account.id) is None

    async def test_proxy_down_keeps_account(
        self,
        db_session: AsyncSession,
        fake_cliproxy: FakeCliproxy,
    ) -> None:
        account = await _signed_in(db_session, fake_cliproxy)
        account_id = account.id
        fake_cliproxy.down = True

        with pytest.raises(CliproxyUnavailableError):
            await delete_account(db_session, fake_cliproxy.client(), account)

        assert await db_session.get(LlmAccount, account_id) is not None

    @pytest.mark.parametrize("usage", ["start", "current", "history"])
    async def test_used_account_conflicts(
        self,
        db_session: AsyncSession,
        fake_cliproxy: FakeCliproxy,
        usage: str,
    ) -> None:
        account = await _signed_in(db_session, fake_cliproxy)
        if usage == "history":
            task = await make_task(db_session, created_by=account.created_by)
            db_session.add(
                NodeLog(
                    task_id=task.id,
                    trigger_type=NodeLogTriggerType.FREEFORM_MANUAL,
                    llm_account_id=account.id,
                ),
            )
            await db_session.flush()
        else:
            field = "llm_account_id" if usage == "start" else "current_llm_account_id"
            await make_task(db_session, created_by=account.created_by, **{field: account.id})

        with pytest.raises(ConflictError):
            await delete_account(db_session, fake_cliproxy.client(), account)

        assert _CREDENTIAL in fake_cliproxy.credentials
