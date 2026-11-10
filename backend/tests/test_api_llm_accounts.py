"""
`/llm-accounts` (разделы 3.1, 15.1, 19.2, 19.5 ТЗ): аккаунт личный — `user`
видит и меняет только свои, `admin` — все; вход через LLM-прокси, модель из
списка учётки, порядок переключения; аккаунт задачи — только её автора.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import pytest

from db.models.enums import LlmAccountStatus, TaskStatus
from db.models.llm import LlmAccount
from db.models.tasks import Task
from tests.cliproxy_support import FakeCliproxy, NextLogin
from tests.factories import make_llm_account, make_task, make_user

if TYPE_CHECKING:
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession

    from db.models.users import User

_CREDENTIAL = "claude-dev@example.com.json"


async def _task(db_session: AsyncSession, owner_id: uuid.UUID, **fields: Any) -> Task:
    fields.setdefault("status", TaskStatus.NEW)
    return await make_task(db_session, created_by=owner_id, **fields)


def _new(label: str, provider: str) -> dict[str, str]:
    return {"label": label, "provider": provider}


async def _signed_in(
    db_session: AsyncSession,
    api_cliproxy: FakeCliproxy,
    owner_id: uuid.UUID,
) -> LlmAccount:
    account = await make_llm_account(db_session, owner_id=owner_id, credential=_CREDENTIAL)
    api_cliproxy.add_credential(_CREDENTIAL, models=["claude-opus-5-5", "claude-sonnet-5-5"])
    api_cliproxy.credentials[_CREDENTIAL].prefix = account.cliproxy_prefix
    return account


class TestProviders:
    async def test_registry(self, authed_client: AsyncClient) -> None:
        response = await authed_client.get("/llm-accounts/providers")

        assert response.status_code == 200
        assert {item["id"]: item["reports_usage"] for item in response.json()} == {
            "anthropic": True,
            "openai": True,
            "google": False,
            "xai": False,
        }


class TestCreate:
    async def test_owner_and_order(self, authed_client: AsyncClient, current_user: User) -> None:
        first = await authed_client.post("/llm-accounts", json=_new("a", "anthropic"))
        second = await authed_client.post("/llm-accounts", json=_new("b", "openai"))

        assert (first.status_code, second.status_code) == (201, 201)
        body = second.json()
        assert body["created_by"] == str(current_user.id)
        assert (body["switch_order"], body["status"], body["signed_in"]) == (
            2,
            LlmAccountStatus.LOGIN_REQUIRED.value,
            False,
        )
        assert "cliproxy_credential" not in body

    @pytest.mark.parametrize(
        "payload",
        [{"label": "a", "provider": "mistral"}, {"label": "", "provider": "anthropic"}],
        ids=["unknown_provider", "empty_label"],
    )
    async def test_rejected(self, authed_client: AsyncClient, payload: dict[str, str]) -> None:
        response = await authed_client.post("/llm-accounts", json=payload)

        assert response.status_code == 422


class TestList:
    async def test_user_sees_only_own_in_order(
        self,
        authed_client: AsyncClient,
        current_user: User,
        db_session: AsyncSession,
    ) -> None:
        other = await make_user(db_session)
        first = await make_llm_account(db_session, owner_id=current_user.id, label="я")
        second = await make_llm_account(db_session, owner_id=current_user.id, label="а")
        await make_llm_account(db_session, owner_id=other.id)

        ids = [item["id"] for item in (await authed_client.get("/llm-accounts")).json()]

        assert ids == [str(first.id), str(second.id)]

    async def test_admin_sees_all(
        self,
        admin_client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        other = await make_user(db_session)
        foreign = await make_llm_account(db_session, owner_id=other.id)

        ids = {item["id"] for item in (await admin_client.get("/llm-accounts")).json()}

        assert str(foreign.id) in ids


class TestOrder:
    async def test_reorder(
        self,
        authed_client: AsyncClient,
        current_user: User,
        db_session: AsyncSession,
    ) -> None:
        first = await make_llm_account(db_session, owner_id=current_user.id)
        second = await make_llm_account(db_session, owner_id=current_user.id)

        response = await authed_client.put(
            "/llm-accounts/order",
            json={"account_ids": [str(second.id), str(first.id)]},
        )

        assert response.status_code == 200, response.text
        assert [(item["id"], item["switch_order"]) for item in response.json()] == [
            (str(second.id), 1),
            (str(first.id), 2),
        ]

    async def test_foreign_account_rejected(
        self,
        authed_client: AsyncClient,
        current_user: User,
        db_session: AsyncSession,
    ) -> None:
        own = await make_llm_account(db_session, owner_id=current_user.id)
        foreign = await make_llm_account(db_session, owner_id=(await make_user(db_session)).id)

        response = await authed_client.put(
            "/llm-accounts/order",
            json={"account_ids": [str(own.id), str(foreign.id)]},
        )

        assert response.status_code == 422


class TestForeignAccount:
    @pytest.mark.parametrize(
        ("method", "path", "payload"),
        [
            ("get", "", None),
            ("patch", "", {"label": "чужой"}),
            ("delete", "", None),
            ("get", "/models", None),
            ("post", "/login", None),
            ("get", "/login/status", None),
        ],
    )
    async def test_is_404(
        self,
        authed_client: AsyncClient,
        api_cliproxy: FakeCliproxy,
        db_session: AsyncSession,
        method: str,
        path: str,
        payload: dict[str, str] | None,
    ) -> None:
        other = await make_user(db_session)
        foreign = await make_llm_account(db_session, owner_id=other.id)
        kwargs = {"json": payload} if payload is not None else {}

        response = await getattr(authed_client, method)(
            f"/llm-accounts/{foreign.id}{path}",
            **kwargs,
        )

        assert response.status_code == 404

    async def test_admin_changes_foreign(
        self,
        admin_client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        other = await make_user(db_session)
        foreign = await make_llm_account(db_session, owner_id=other.id)

        response = await admin_client.patch(f"/llm-accounts/{foreign.id}", json={"label": "новое"})

        assert response.status_code == 200
        assert response.json()["label"] == "новое"


class TestUpdate:
    async def test_model_and_effort(
        self,
        authed_client: AsyncClient,
        api_cliproxy: FakeCliproxy,
        current_user: User,
        db_session: AsyncSession,
    ) -> None:
        account = await _signed_in(db_session, api_cliproxy, current_user.id)

        response = await authed_client.patch(
            f"/llm-accounts/{account.id}",
            json={"default_model": "claude-sonnet-5-5", "default_effort": "xhigh"},
        )

        assert response.status_code == 200, response.text
        assert (response.json()["default_model"], response.json()["default_effort"]) == (
            "claude-sonnet-5-5",
            "xhigh",
        )

    async def test_model_outside_list(
        self,
        authed_client: AsyncClient,
        api_cliproxy: FakeCliproxy,
        current_user: User,
        db_session: AsyncSession,
    ) -> None:
        account = await _signed_in(db_session, api_cliproxy, current_user.id)

        response = await authed_client.patch(
            f"/llm-accounts/{account.id}",
            json={"default_model": "gpt-6-sol"},
        )

        assert response.status_code == 422

    async def test_models_listed_without_prefix(
        self,
        authed_client: AsyncClient,
        api_cliproxy: FakeCliproxy,
        current_user: User,
        db_session: AsyncSession,
    ) -> None:
        account = await _signed_in(db_session, api_cliproxy, current_user.id)

        response = await authed_client.get(f"/llm-accounts/{account.id}/models")

        assert response.json() == ["claude-opus-5-5", "claude-sonnet-5-5"]

    async def test_disable(
        self,
        authed_client: AsyncClient,
        api_cliproxy: FakeCliproxy,
        current_user: User,
        db_session: AsyncSession,
    ) -> None:
        account = await _signed_in(db_session, api_cliproxy, current_user.id)

        response = await authed_client.patch(f"/llm-accounts/{account.id}", json={"enabled": False})

        assert response.json()["status"] == LlmAccountStatus.DISABLED.value
        assert api_cliproxy.credentials[_CREDENTIAL].disabled is True

    async def test_proxy_down_is_502(
        self,
        authed_client: AsyncClient,
        api_cliproxy: FakeCliproxy,
        current_user: User,
        db_session: AsyncSession,
    ) -> None:
        account = await _signed_in(db_session, api_cliproxy, current_user.id)
        api_cliproxy.down = True

        response = await authed_client.patch(f"/llm-accounts/{account.id}", json={"enabled": False})

        assert response.status_code == 502


class TestLogin:
    async def test_full_flow(
        self,
        authed_client: AsyncClient,
        api_cliproxy: FakeCliproxy,
        current_user: User,
        db_session: AsyncSession,
    ) -> None:
        account = await make_llm_account(
            db_session,
            owner_id=current_user.id,
            status=LlmAccountStatus.LOGIN_REQUIRED,
        )
        api_cliproxy.next_login = NextLogin(name=_CREDENTIAL, returns_auth_id=False)

        start = await authed_client.post(f"/llm-accounts/{account.id}/login")
        waiting = await authed_client.get(f"/llm-accounts/{account.id}/login/status")
        done = await authed_client.post(
            f"/llm-accounts/{account.id}/login/callback",
            json={"redirect_url": "http://localhost:54545/callback?code=c"},
        )

        assert start.json()["url"].startswith("https://auth.example.com/")
        assert datetime.fromisoformat(start.json()["expires_at"]) > datetime.now(UTC)
        assert waiting.json() == {"state": "wait", "error": None}
        assert done.json() == {"state": "ok", "error": None}
        listed = (await authed_client.get(f"/llm-accounts/{account.id}")).json()
        assert (listed["signed_in"], listed["status"]) == (True, LlmAccountStatus.ACTIVE.value)
        assert api_cliproxy.credentials[_CREDENTIAL].prefix == account.cliproxy_prefix

    async def test_cancel(
        self,
        authed_client: AsyncClient,
        api_cliproxy: FakeCliproxy,
        current_user: User,
        db_session: AsyncSession,
    ) -> None:
        account = await make_llm_account(db_session, owner_id=current_user.id)
        start = (await authed_client.post(f"/llm-accounts/{account.id}/login")).json()

        response = await authed_client.delete(f"/llm-accounts/{account.id}/login")

        assert response.status_code == 204
        assert api_cliproxy.cancelled == [start["state"]]

    async def test_not_redirect_rejected(
        self,
        authed_client: AsyncClient,
        api_cliproxy: FakeCliproxy,
        current_user: User,
        db_session: AsyncSession,
    ) -> None:
        account = await make_llm_account(db_session, owner_id=current_user.id)
        await authed_client.post(f"/llm-accounts/{account.id}/login")

        response = await authed_client.post(
            f"/llm-accounts/{account.id}/login/callback",
            json={"redirect_url": "не адрес"},
        )

        assert response.status_code == 422
        assert "адрес после входа" in response.json()["error"]["message"]
        assert ("POST", "/oauth/callback") not in api_cliproxy.requests

    async def test_callback_without_login(
        self,
        authed_client: AsyncClient,
        api_cliproxy: FakeCliproxy,
        current_user: User,
        db_session: AsyncSession,
    ) -> None:
        account = await make_llm_account(db_session, owner_id=current_user.id)

        response = await authed_client.post(
            f"/llm-accounts/{account.id}/login/callback",
            json={"redirect_url": "http://localhost/cb"},
        )

        assert response.json()["state"] == "error"


class TestDelete:
    async def test_unused_removes_credential(
        self,
        authed_client: AsyncClient,
        api_cliproxy: FakeCliproxy,
        current_user: User,
        db_session: AsyncSession,
    ) -> None:
        account = await _signed_in(db_session, api_cliproxy, current_user.id)

        response = await authed_client.delete(f"/llm-accounts/{account.id}")

        assert response.status_code == 204
        assert api_cliproxy.credentials == {}

    async def test_used_by_task(
        self,
        authed_client: AsyncClient,
        api_cliproxy: FakeCliproxy,
        current_user: User,
        db_session: AsyncSession,
    ) -> None:
        account = await make_llm_account(db_session, owner_id=current_user.id)
        await _task(db_session, current_user.id, llm_account_id=account.id)

        response = await authed_client.delete(f"/llm-accounts/{account.id}")

        assert response.status_code == 409


class TestThresholds:
    async def test_saved_in_profile(self, authed_client: AsyncClient) -> None:
        before = (await authed_client.get("/profile")).json()

        response = await authed_client.put(
            "/profile/llm-thresholds",
            json={"five_hour_pct": 80, "week_pct": 50},
        )

        assert before["llm_switch_threshold_5h_pct"] == 93
        body = response.json()
        assert body["llm_switch_threshold_5h_pct"] == 80
        assert "llm_switch_threshold_week_pct" not in body

    @pytest.mark.parametrize("five_hour", [0, 101, None])
    async def test_out_of_range(self, authed_client: AsyncClient, five_hour: int | None) -> None:
        response = await authed_client.put(
            "/profile/llm-thresholds",
            json={"five_hour_pct": five_hour},
        )

        assert response.status_code == 422


class TestCompactOnSwitch:
    async def test_toggled(self, authed_client: AsyncClient) -> None:
        before = (await authed_client.get("/profile")).json()

        response = await authed_client.put("/profile/llm-compact", json={"enabled": False})

        assert before["llm_compact_on_switch"] is True
        assert response.json()["llm_compact_on_switch"] is False
        assert (await authed_client.get("/profile")).json()["llm_compact_on_switch"] is False

    @pytest.mark.parametrize("body", [{}, {"enabled": "maybe"}])
    async def test_invalid(self, authed_client: AsyncClient, body: dict[str, object]) -> None:
        response = await authed_client.put("/profile/llm-compact", json=body)

        assert response.status_code == 422


class TestTaskAccount:
    """Раздел 19.2: LLM-аккаунт задачи — только один из аккаунтов её автора."""

    async def test_create_with_foreign_account(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        other = await make_user(db_session)
        foreign = await make_llm_account(db_session, owner_id=other.id)

        response = await authed_client.post(
            "/tasks",
            json={
                "code": "RR-20001",
                "title": "t",
                "description": "d",
                "llm_account_id": str(foreign.id),
            },
        )

        assert response.status_code == 404

    async def test_admin_sets_own_account_on_foreign_task(
        self,
        admin_client: AsyncClient,
        admin_user: User,
        db_session: AsyncSession,
    ) -> None:
        author = await make_user(db_session)
        task = await _task(db_session, author.id)
        admin_account = await make_llm_account(db_session, owner_id=admin_user.id)
        author_account = await make_llm_account(db_session, owner_id=author.id)

        rejected = await admin_client.patch(
            f"/tasks/{task.id}",
            json={"llm_account_id": str(admin_account.id)},
        )
        accepted = await admin_client.patch(
            f"/tasks/{task.id}",
            json={"llm_account_id": str(author_account.id)},
        )

        assert rejected.status_code == 404
        assert accepted.status_code == 200

    async def test_duplicate_with_foreign_account(
        self,
        authed_client: AsyncClient,
        current_user: User,
        db_session: AsyncSession,
    ) -> None:
        other = await make_user(db_session)
        foreign = await make_llm_account(db_session, owner_id=other.id)
        source = await _task(db_session, current_user.id, status=TaskStatus.DONE)

        response = await authed_client.post(
            f"/tasks/{source.id}/duplicate",
            json={
                "code": "RR-20002",
                "title": "t",
                "description": "d",
                "llm_account_id": str(foreign.id),
            },
        )

        assert response.status_code == 404
