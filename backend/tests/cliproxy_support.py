"""
Фейковый management API CLIProxyAPI для тестов: состояние учёток и входов в
памяти, ответы в формате прокси v8.0.48 (`docs/remote_control_findings.md`).
Подключается к настоящему `CliproxyManagementClient` через `httpx.MockTransport`.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import Any

import httpx

from clients.cliproxy import CliproxyManagementClient, CliproxySettings

_API = "/v8/management"
LATEST_VERSION = "v8.0.50"


def _unknown_state() -> httpx.Response:
    return httpx.Response(404, json={"status": "error", "error": "unknown or expired state"})


@dataclass
class FakeCredential:
    name: str
    provider: str
    auth_index: str
    models: list[str]
    prefix: str | None = None
    disabled: bool = False
    requires_sign_in: bool = False


@dataclass
class _Session:
    provider: str
    target: str | None
    status: str = "wait"
    error: str | None = None
    created: str | None = None


@dataclass
class NextLogin:
    """Что создаст следующий вход: имя учётки и вернёт ли прокси его в `auth_id`."""

    name: str
    returns_auth_id: bool
    models: list[str] = field(default_factory=lambda: ["claude-opus-5-5", "claude-sonnet-5-5"])
    error: str | None = None


class FakeCliproxy:
    def __init__(self) -> None:
        self.credentials: dict[str, FakeCredential] = {}
        self.sessions: dict[str, _Session] = {}
        self.cancelled: list[str] = []
        self.next_login: NextLogin | None = None
        # Ответы `requests/api-call` по адресу провайдера: (status_code, body).
        self.api_responses: dict[str, tuple[int, str]] = {}
        self.api_calls: list[dict[str, Any]] = []
        self.down = False
        self.latest_available = True
        # Тела вызовов обновления токена и снятия паузы.
        self.refreshed: list[str] = []
        self.cooldown_resets: list[str] = []
        self.requests: list[tuple[str, str]] = []

    def client(self) -> CliproxyManagementClient:
        return CliproxyManagementClient(
            settings=CliproxySettings(url="http://cliproxy:8317", management_key="fake-key"),
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(self._handle)),
        )

    def add_credential(
        self,
        name: str,
        *,
        provider: str = "claude",
        models: list[str] | None = None,
    ) -> FakeCredential:
        credential = FakeCredential(
            name=name,
            provider=provider,
            auth_index=f"idx-{len(self.credentials) + 1}",
            models=models if models is not None else ["claude-opus-5-5"],
        )
        self.credentials[name] = credential
        return credential

    def _handle(self, request: httpx.Request) -> httpx.Response:
        if self.down:
            raise httpx.ConnectError("connection refused", request=request)
        path = request.url.path.removeprefix(_API)
        self.requests.append((request.method, path))
        params = dict(request.url.params)
        body = json.loads(request.content) if request.content else {}
        handler = _ROUTES.get((request.method, path))
        if handler is None:
            return httpx.Response(404, json={"error": "not found"})
        return handler(self, params, body)

    def _auth_url(self, params: dict[str, str], _: dict[str, Any]) -> httpx.Response:
        state = uuid.uuid4().hex
        self.sessions[state] = _Session(provider=params["provider"], target=params.get("name"))
        url = f"https://auth.example.com/{state}"
        return httpx.Response(200, json={"status": "ok", "url": url, "state": state})

    def _callback(self, _: dict[str, str], body: dict[str, Any]) -> httpx.Response:
        session = self.sessions.get(body.get("state", ""))
        if session is None:
            return _unknown_state()
        login = self.next_login
        if login is not None and login.error is not None:
            session.status, session.error = "error", login.error
            return httpx.Response(200, json={"status": "ok"})
        if session.target is not None:
            session.status, session.created = "ok", session.target
            return httpx.Response(200, json={"status": "ok"})
        assert login is not None, "тест не задал next_login"
        if login.name not in self.credentials:
            self.add_credential(login.name, provider=session.provider, models=login.models)
        session.status = "ok"
        session.created = login.name if login.returns_auth_id else None
        return httpx.Response(200, json={"status": "ok"})

    def _status(self, params: dict[str, str], _: dict[str, Any]) -> httpx.Response:
        session = self.sessions.get(params.get("state", ""))
        if session is None:
            return _unknown_state()
        payload: dict[str, Any] = {"status": session.status}
        if session.error:
            payload["error"] = session.error
        if session.created:
            payload["auth_id"] = session.created
        return httpx.Response(200, json=payload)

    def _cancel(self, params: dict[str, str], _: dict[str, Any]) -> httpx.Response:
        state = params.get("state", "")
        if self.sessions.pop(state, None) is None:
            return httpx.Response(400, json={"status": "error", "error": "invalid state"})
        self.cancelled.append(state)
        return httpx.Response(200, json={"status": "ok", "cancelled": True})

    def _list(self, _: dict[str, str], __: dict[str, Any]) -> httpx.Response:
        files = [
            {
                "name": credential.name,
                "provider": credential.provider,
                "auth_index": credential.auth_index,
                "disabled": credential.disabled,
                "requires_sign_in": credential.requires_sign_in,
                "quota_blocked": False,
                "status": "active",
            }
            for credential in self.credentials.values()
        ]
        return httpx.Response(200, json={"files": files})

    def _credential_or_404(self, name: str | None) -> FakeCredential | httpx.Response:
        credential = self.credentials.get(name or "")
        if credential is None:
            return httpx.Response(404, json={"error": "auth file not found"})
        return credential

    def _models(self, params: dict[str, str], _: dict[str, Any]) -> httpx.Response:
        credential = self._credential_or_404(params.get("name"))
        if isinstance(credential, httpx.Response):
            return credential
        prefix = f"{credential.prefix}/" if credential.prefix else ""
        models = [{"id": f"{prefix}{model}"} for model in credential.models]
        return httpx.Response(200, json={"models": models})

    def _fields(self, _: dict[str, str], body: dict[str, Any]) -> httpx.Response:
        credential = self._credential_or_404(body.get("name"))
        if isinstance(credential, httpx.Response):
            return credential
        credential.prefix = body.get("prefix")
        return httpx.Response(200, json={"status": "ok"})

    def _set_status(self, _: dict[str, str], body: dict[str, Any]) -> httpx.Response:
        credential = self._credential_or_404(body.get("name"))
        if isinstance(credential, httpx.Response):
            return credential
        credential.disabled = bool(body["disabled"])
        return httpx.Response(200, json={"status": "ok", "disabled": credential.disabled})

    def _delete(self, params: dict[str, str], _: dict[str, Any]) -> httpx.Response:
        if self.credentials.pop(params.get("name", ""), None) is None:
            return httpx.Response(404, json={"error": "auth file not found"})
        return httpx.Response(200, json={"status": "ok"})

    def _refresh(self, _: dict[str, str], body: dict[str, Any]) -> httpx.Response:
        self.refreshed.append(body["name"])
        return httpx.Response(200, json={"status": "ok"})

    def _cooldown_reset(self, _: dict[str, str], body: dict[str, Any]) -> httpx.Response:
        self.cooldown_resets.append(body["auth_index"])
        return httpx.Response(200, json={"status": "ok"})

    def _api_call(self, _: dict[str, str], body: dict[str, Any]) -> httpx.Response:
        self.api_calls.append(body)
        status_code, response_body = self.api_responses.get(body["url"], (404, "{}"))
        payload = {"status_code": status_code, "header": {}, "body": response_body}
        return httpx.Response(200, json=payload)

    def _latest(self, _: dict[str, str], __: dict[str, Any]) -> httpx.Response:
        if not self.latest_available:
            return httpx.Response(502, json={"error": "github unavailable"})
        return httpx.Response(200, json={"latest-version": LATEST_VERSION})


_ROUTES = {
    ("GET", "/oauth/auth-url"): FakeCliproxy._auth_url,
    ("POST", "/oauth/callback"): FakeCliproxy._callback,
    ("GET", "/oauth/status"): FakeCliproxy._status,
    ("DELETE", "/oauth/session"): FakeCliproxy._cancel,
    ("GET", "/credentials"): FakeCliproxy._list,
    ("GET", "/credentials/models"): FakeCliproxy._models,
    ("PATCH", "/credentials/fields"): FakeCliproxy._fields,
    ("PATCH", "/credentials/status"): FakeCliproxy._set_status,
    ("DELETE", "/credentials"): FakeCliproxy._delete,
    ("POST", "/credentials/refresh"): FakeCliproxy._refresh,
    ("POST", "/routing/cooldown/reset"): FakeCliproxy._cooldown_reset,
    ("POST", "/requests/api-call"): FakeCliproxy._api_call,
    ("GET", "/server/latest-version"): FakeCliproxy._latest,
}
