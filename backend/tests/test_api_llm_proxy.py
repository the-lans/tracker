"""
`/llm-proxy` (раздел 15.5 ТЗ): состояние LLM-прокси для администратора —
учётки с владельцем и «без владельца», обновление токена, снятие паузы,
удаление учётки без аккаунта.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

import pytest

from tests.cliproxy_support import LATEST_VERSION, FakeCliproxy
from tests.factories import make_llm_account

if TYPE_CHECKING:
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession

    from db.models.users import User

_BOUND = "claude-dev@example.com.json"
_ORPHAN = "codex-orphan@example.com.json"


async def _bound_and_orphan(
    db_session: AsyncSession,
    api_cliproxy: FakeCliproxy,
    owner: User,
) -> None:
    account = await make_llm_account(
        db_session,
        owner_id=owner.id,
        credential=_BOUND,
        label="main",
    )
    account.usage_5h_pct = Decimal("42.50")
    await db_session.flush()
    api_cliproxy.add_credential(_BOUND)
    api_cliproxy.add_credential(_ORPHAN, provider="codex")


class TestState:
    async def test_credentials_with_owner(
        self,
        admin_client: AsyncClient,
        admin_user: User,
        db_session: AsyncSession,
        api_cliproxy: FakeCliproxy,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("CLIPROXY_VERSION", "v8.0.48")
        await _bound_and_orphan(db_session, api_cliproxy, admin_user)

        response = await admin_client.get("/llm-proxy")

        assert response.status_code == 200
        body = response.json()
        assert (body["available"], body["version"], body["latest_version"]) == (
            True,
            "v8.0.48",
            LATEST_VERSION,
        )
        owners = {
            item["name"]: (item["account_label"], item["owner_email"], item["usage_5h_pct"])
            for item in body["credentials"]
        }
        assert owners == {
            _BOUND: ("main", admin_user.email, "42.50"),
            _ORPHAN: (None, None, None),
        }

    async def test_proxy_down(
        self,
        admin_client: AsyncClient,
        api_cliproxy: FakeCliproxy,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("CLIPROXY_VERSION", raising=False)
        api_cliproxy.down = True

        response = await admin_client.get("/llm-proxy")

        assert response.status_code == 200
        body = response.json()
        assert (body["available"], body["version"], body["credentials"]) == (
            False,
            "unknown",
            [],
        )
        assert body["error"]

    async def test_latest_version_unknown(
        self,
        admin_client: AsyncClient,
        api_cliproxy: FakeCliproxy,
    ) -> None:
        api_cliproxy.latest_available = False

        body = (await admin_client.get("/llm-proxy")).json()

        assert (body["available"], body["latest_version"]) == (True, None)

    @pytest.mark.parametrize(
        ("method", "path"),
        [
            ("GET", "/llm-proxy"),
            ("POST", "/llm-proxy/credentials/refresh"),
            ("POST", "/llm-proxy/credentials/cooldown/reset"),
            ("DELETE", f"/llm-proxy/credentials?name={_ORPHAN}"),
        ],
    )
    async def test_admin_only(
        self,
        authed_client: AsyncClient,
        api_cliproxy: FakeCliproxy,
        method: str,
        path: str,
    ) -> None:
        api_cliproxy.add_credential(_ORPHAN, provider="codex")
        payload = {"name": _ORPHAN} if method == "POST" else None

        response = await authed_client.request(method, path, json=payload)

        assert response.status_code == 403
        assert _ORPHAN in api_cliproxy.credentials
        assert (api_cliproxy.refreshed, api_cliproxy.cooldown_resets) == ([], [])


class TestActions:
    async def test_refresh(self, admin_client: AsyncClient, api_cliproxy: FakeCliproxy) -> None:
        api_cliproxy.add_credential(_ORPHAN, provider="codex")

        response = await admin_client.post(
            "/llm-proxy/credentials/refresh",
            json={"name": _ORPHAN},
        )

        assert (response.status_code, api_cliproxy.refreshed) == (204, [_ORPHAN])

    async def test_cooldown_reset_by_auth_index(
        self,
        admin_client: AsyncClient,
        api_cliproxy: FakeCliproxy,
    ) -> None:
        api_cliproxy.add_credential(_BOUND)
        credential = api_cliproxy.add_credential(_ORPHAN, provider="codex")

        response = await admin_client.post(
            "/llm-proxy/credentials/cooldown/reset",
            json={"name": _ORPHAN},
        )

        assert response.status_code == 204
        assert api_cliproxy.cooldown_resets == [credential.auth_index]

    @pytest.mark.parametrize(
        "path",
        ["/llm-proxy/credentials/refresh", "/llm-proxy/credentials/cooldown/reset"],
    )
    async def test_unknown_credential(
        self,
        admin_client: AsyncClient,
        api_cliproxy: FakeCliproxy,
        path: str,
    ) -> None:
        response = await admin_client.post(path, json={"name": _ORPHAN})

        assert response.status_code == 404
        assert (api_cliproxy.refreshed, api_cliproxy.cooldown_resets) == ([], [])

    async def test_proxy_down_is_502(
        self,
        admin_client: AsyncClient,
        api_cliproxy: FakeCliproxy,
    ) -> None:
        api_cliproxy.down = True

        response = await admin_client.post(
            "/llm-proxy/credentials/refresh",
            json={"name": _ORPHAN},
        )

        assert response.status_code == 502


class TestDeleteOrphan:
    async def test_orphan_deleted(
        self,
        admin_client: AsyncClient,
        admin_user: User,
        db_session: AsyncSession,
        api_cliproxy: FakeCliproxy,
    ) -> None:
        await _bound_and_orphan(db_session, api_cliproxy, admin_user)

        response = await admin_client.delete("/llm-proxy/credentials", params={"name": _ORPHAN})

        assert response.status_code == 204
        assert set(api_cliproxy.credentials) == {_BOUND}

    @pytest.mark.parametrize(
        ("name", "status_code"),
        [(_BOUND, 409), ("missing@example.com.json", 404)],
        ids=["bound", "missing"],
    )
    async def test_refused(
        self,
        admin_client: AsyncClient,
        admin_user: User,
        db_session: AsyncSession,
        api_cliproxy: FakeCliproxy,
        name: str,
        status_code: int,
    ) -> None:
        await _bound_and_orphan(db_session, api_cliproxy, admin_user)

        response = await admin_client.delete("/llm-proxy/credentials", params={"name": name})

        assert response.status_code == status_code
        assert set(api_cliproxy.credentials) == {_BOUND, _ORPHAN}
