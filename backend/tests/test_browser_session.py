"""Контракт браузерной сессии и отказ небезопасным запросам."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

import pytest
from fastapi import Response

from services.auth_tokens import issue_session_token
from services.browser_session import clear_session_cookie, session_cookie_name, set_session_cookie
from tests.factories import make_user

if TYPE_CHECKING:
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession


class TestBrowserSession:
    @pytest.mark.parametrize("dev", [False, True])
    def test_cookie_flags(self, monkeypatch: pytest.MonkeyPatch, dev: bool) -> None:
        monkeypatch.setenv("TRACKER_DEV_COOKIE", str(dev).lower())
        response = Response()
        set_session_cookie(response, "secret")
        cookie = response.headers["set-cookie"]
        assert session_cookie_name() == ("tracker_dev_session" if dev else "__Host-tracker_session")
        assert "HttpOnly" in cookie and "SameSite=lax" in cookie and "Path=/" in cookie
        assert "Max-Age=604800" in cookie and "Domain=" not in cookie
        assert ("Secure" in cookie) is not dev
        deleted = Response()
        clear_session_cookie(deleted)
        assert "Max-Age=0" in deleted.headers["set-cookie"]
        assert deleted.headers["set-cookie"].startswith(session_cookie_name() + "=")

    @pytest.mark.parametrize(
        "origin", [None, "", "null", "https://evil.example", "https://tracker.botelo.ru.evil"]
    )
    async def test_csrf_origin_rejected(self, api_client: AsyncClient, origin: str | None) -> None:
        api_client.headers.pop("Origin")
        if origin is not None:
            api_client.headers["Origin"] = origin
        response = await api_client.post(
            "/auth/logout",
            headers={"Host": "evil.example", "X-Forwarded-Host": "tracker.botelo.ru"},
        )
        assert response.status_code == 403
        assert "set-cookie" not in response.headers

    async def test_csrf_header_required_and_valid_logout(self, api_client: AsyncClient) -> None:
        api_client.headers.pop("X-Tracker-Request")
        assert (await api_client.post("/auth/logout")).status_code == 403
        response = await api_client.post("/auth/logout", headers={"X-Tracker-Request": "1"})
        assert response.status_code == 204
        assert "Max-Age=0" in response.headers["set-cookie"]

    async def test_cookie_only_me_and_expiry(
        self, api_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        user = await make_user(db_session)
        token = issue_session_token(user.id)
        assert (
            await api_client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
        ).status_code == 401
        api_client.cookies.set(session_cookie_name(), token)
        response = await api_client.get("/auth/me")
        assert response.status_code == 200
        assert response.json()["id"] == str(user.id)
        assert response.headers["cache-control"] == "no-store"
        api_client.cookies.set(
            session_cookie_name(), issue_session_token(user.id, ttl=timedelta(seconds=-1))
        )
        assert (await api_client.get("/auth/me")).status_code == 401
        api_client.cookies.set(session_cookie_name(), "forged")
        assert (await api_client.get("/auth/me")).status_code == 401
