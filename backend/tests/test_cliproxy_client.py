"""Клиент management API CLIProxyAPI (разделы 19.5, 19.7 ТЗ)."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from clients.cliproxy import (
    CliproxyManagementClient,
    CliproxyRequestError,
    CliproxySettings,
    CliproxyUnavailableError,
    Credential,
    OAuthState,
    OAuthStatus,
)

_KEY = "management-key"
_CREDENTIAL = "claude-owner@example.com.json"
_PREFIX = "acc-0123456789ab"

_Reply = httpx.Response | Callable[[httpx.Request], httpx.Response]


class _Proxy:
    """Отвечает заданным ответом и запоминает запросы."""

    def __init__(self, response: _Reply) -> None:
        self._response = response
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if callable(self._response):
            return self._response(request)
        return self._response

    @property
    def last(self) -> httpx.Request:
        return self.requests[-1]

    def last_json(self) -> Any:
        return json.loads(self.last.content)


def _client(proxy: _Proxy) -> CliproxyManagementClient:
    return CliproxyManagementClient(
        settings=CliproxySettings(url="http://cliproxy:8317/", management_key=_KEY),
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(proxy)),
    )


def _ok(payload: dict[str, Any] | None = None) -> httpx.Response:
    return httpx.Response(200, json=payload if payload is not None else {"status": "ok"})


class TestRequests:
    async def test_management_key_and_base_path(self) -> None:
        proxy = _Proxy(_ok({"latest-version": "v8.0.50"}))

        assert await _client(proxy).latest_version() == "v8.0.50"

        assert proxy.last.headers["Authorization"] == f"Bearer {_KEY}"
        assert str(proxy.last.url) == "http://cliproxy:8317/v8/management/server/latest-version"

    @pytest.mark.parametrize(
        ("call", "method", "path", "params", "body"),
        [
            (
                lambda c: c.oauth_callback(provider="claude", state="s1", redirect_url="http://cb"),
                "POST",
                "/oauth/callback",
                {},
                {"provider": "claude", "state": "s1", "redirect_url": "http://cb"},
            ),
            (lambda c: c.oauth_cancel("s1"), "DELETE", "/oauth/session", {"state": "s1"}, None),
            (
                lambda c: c.set_credential_prefix(_CREDENTIAL, "acc-0123456789ab"),
                "PATCH",
                "/credentials/fields",
                {},
                {"name": _CREDENTIAL, "prefix": "acc-0123456789ab"},
            ),
            (
                lambda c: c.set_credential_disabled(_CREDENTIAL, disabled=True),
                "PATCH",
                "/credentials/status",
                {},
                {"name": _CREDENTIAL, "disabled": True},
            ),
            (
                lambda c: c.delete_credential(_CREDENTIAL),
                "DELETE",
                "/credentials",
                {"name": _CREDENTIAL},
                None,
            ),
            (
                lambda c: c.refresh_credential(_CREDENTIAL),
                "POST",
                "/credentials/refresh",
                {},
                {"name": _CREDENTIAL},
            ),
            (
                lambda c: c.reset_cooldown("idx-1"),
                "POST",
                "/routing/cooldown/reset",
                {},
                {"auth_index": "idx-1"},
            ),
        ],
    )
    async def test_commands(
        self,
        call: Callable[[CliproxyManagementClient], Any],
        method: str,
        path: str,
        params: dict[str, str],
        body: dict[str, Any] | None,
    ) -> None:
        proxy = _Proxy(_ok())

        await call(_client(proxy))

        assert proxy.last.method == method
        assert proxy.last.url.path == f"/v8/management{path}"
        assert dict(proxy.last.url.params) == params
        assert (proxy.last_json() if proxy.last.content else None) == body


class TestOAuth:
    @pytest.mark.parametrize(
        ("credential", "params"),
        [
            (None, {"provider": "codex"}),
            (_CREDENTIAL, {"provider": "codex", "name": _CREDENTIAL}),
        ],
    )
    async def test_auth_url(self, credential: str | None, params: dict[str, str]) -> None:
        proxy = _Proxy(_ok({"status": "ok", "url": "https://auth.example.com/x", "state": "s1"}))

        start = await _client(proxy).oauth_auth_url(provider="codex", credential=credential)

        assert (start.url, start.state) == ("https://auth.example.com/x", "s1")
        assert dict(proxy.last.url.params) == params

    @pytest.mark.parametrize(
        ("response", "expected"),
        [
            (_ok({"status": "wait"}), OAuthStatus(OAuthState.WAIT, None, None)),
            (_ok({"status": "ok"}), OAuthStatus(OAuthState.OK, None, None)),
            (
                _ok({"status": "ok", "auth_id": _CREDENTIAL, "requires_sign_in": False}),
                OAuthStatus(OAuthState.OK, _CREDENTIAL, None),
            ),
            (
                httpx.Response(404, json={"status": "error", "error": "unknown or expired state"}),
                OAuthStatus(OAuthState.ERROR, None, "unknown or expired state"),
            ),
        ],
    )
    async def test_status(self, response: httpx.Response, expected: OAuthStatus) -> None:
        proxy = _Proxy(response)

        assert await _client(proxy).oauth_status("s1") == expected
        assert dict(proxy.last.url.params) == {"state": "s1"}


class TestCredentials:
    async def test_list(self) -> None:
        files = [
            {
                "name": _CREDENTIAL,
                "provider": "claude",
                "email": "owner@example.com",
                "auth_index": "idx-1",
                "prefix": "acc-0123456789ab",
                "disabled": False,
                "requires_sign_in": True,
                "quota_blocked": False,
                "status": "active",
            },
            {"id": "codex-other@example.com.json", "type": "codex", "auth_index": "idx-2"},
        ]
        proxy = _Proxy(_ok({"files": files}))

        credentials = await _client(proxy).list_credentials()

        assert credentials == [
            Credential(
                name=_CREDENTIAL,
                provider="claude",
                auth_index="idx-1",
                prefix="acc-0123456789ab",
                disabled=False,
                requires_sign_in=True,
                quota_blocked=False,
                status="active",
            ),
            Credential(
                name="codex-other@example.com.json",
                provider="codex",
                auth_index="idx-2",
                prefix=None,
                disabled=False,
                requires_sign_in=False,
                quota_blocked=False,
                status=None,
            ),
        ]

    async def test_models(self) -> None:
        models = {"models": [{"id": f"{_PREFIX}/claude-opus-5-5"}, {"id": f"{_PREFIX}/x"}]}
        proxy = _Proxy(_ok(models))

        result = await _client(proxy).credential_models(_CREDENTIAL)

        assert result == [f"{_PREFIX}/claude-opus-5-5", f"{_PREFIX}/x"]
        assert dict(proxy.last.url.params) == {"name": _CREDENTIAL}

    async def test_api_call(self) -> None:
        proxy = _Proxy(_ok({"status_code": 200, "header": {}, "body": '{"five_hour": {}}'}))

        result = await _client(proxy).api_call(
            auth_index="idx-1",
            method="GET",
            url="https://api.example.com/usage",
            headers={"Authorization": "Bearer $TOKEN$"},
        )

        assert (result.status_code, result.body) == (200, '{"five_hour": {}}')
        assert proxy.last_json() == {
            "auth_index": "idx-1",
            "method": "GET",
            "url": "https://api.example.com/usage",
            "header": {"Authorization": "Bearer $TOKEN$"},
        }


def _refuse(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("connection refused", request=request)


class TestFailures:
    @pytest.mark.parametrize(
        "response",
        [httpx.Response(503, text="down"), httpx.Response(429, text="slow down"), _refuse],
    )
    async def test_unavailable(
        self,
        response: _Reply,
    ) -> None:
        with pytest.raises(CliproxyUnavailableError) as exc_info:
            await _client(_Proxy(response)).list_credentials()

        assert (exc_info.value.status_code, exc_info.value.is_transient) == (502, True)

    @pytest.mark.parametrize("status", [400, 401, 404])
    async def test_rejected(self, status: int) -> None:
        response = httpx.Response(status, json={"error": "auth file not found"})

        with pytest.raises(CliproxyRequestError) as exc_info:
            await _client(_Proxy(response)).set_credential_prefix(_CREDENTIAL, "acc-1")

        assert exc_info.value.response_status == status
        assert exc_info.value.is_transient is False
        assert "auth file not found" in exc_info.value.message
