"""
Обёртка над management API CLIProxyAPI (`/v8/management`, разделы 19.5, 19.7 ТЗ).

Трекер управляет прокси только через этот API: вход OAuth и привязка учётки к
аккаунту, префикс и статус учётки, её модели, удаление, опрос расхода окон
лимита запросом от имени учётки (`requests/api-call` — токены трекеру не
выдаются) и состояние для администратора. Эндпоинты, меняющие конфигурацию
прокси, не вызываются: её задаёт шаблон из репозитория (раздел 20.3).

Имя учётки содержит email подписки — в логи оно не пишется.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import httpx

from clients.http_errors import HttpFailure, classify_status
from services.errors import ExternalServiceError

_API_PATH = "/v8/management"
_DEFAULT_URL = "http://cliproxy:8317"
_URL_ENV_VAR = "CLIPROXY_MANAGEMENT_URL"
_KEY_ENV_VAR = "CLIPROXY_MANAGEMENT_KEY"
# Раздел 19.7: таймаут вызова management API.
TIMEOUT_SECONDS = 10.0
_LATEST_VERSION_FIELD = "latest-version"


class CliproxyUnavailableError(ExternalServiceError):
    """Прокси недоступен или ответил ошибкой сервера — API трекера отвечает 502."""

    def __init__(self, message: str) -> None:
        super().__init__(message, is_transient=True)


class CliproxyRequestError(ExternalServiceError):
    """Прокси отклонил запрос (4xx): неверный ключ, неизвестная учётка или вход."""

    def __init__(self, message: str, *, status_code: int) -> None:
        super().__init__(message, is_transient=False)
        self.response_status = status_code


class OAuthState(StrEnum):
    WAIT = "wait"
    OK = "ok"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class OAuthStart:
    url: str
    state: str


@dataclass(frozen=True, slots=True)
class OAuthStatus:
    state: OAuthState
    # Имя созданной учётки; прокси отдаёт его не для всех провайдеров (вход Claude — нет).
    credential: str | None
    error: str | None


@dataclass(frozen=True, slots=True)
class Credential:
    name: str
    provider: str
    auth_index: str
    # Список учёток прокси v8.0.48 префикс не отдаёт — он виден в именах моделей учётки.
    prefix: str | None
    disabled: bool
    requires_sign_in: bool
    quota_blocked: bool
    status: str | None


@dataclass(frozen=True, slots=True)
class ApiCallResult:
    status_code: int
    body: str


@dataclass(frozen=True, slots=True)
class CliproxySettings:
    url: str
    management_key: str

    @classmethod
    def from_env(cls) -> CliproxySettings:
        return cls(
            url=os.environ.get(_URL_ENV_VAR, _DEFAULT_URL),
            management_key=os.environ.get(_KEY_ENV_VAR, ""),
        )


def _optional_str(value: object) -> str | None:
    return str(value) if value not in (None, "") else None


def _credential(item: Mapping[str, Any]) -> Credential:
    return Credential(
        name=str(item.get("name") or item.get("id") or ""),
        provider=str(item.get("provider") or item.get("type") or ""),
        auth_index=str(item.get("auth_index") or ""),
        prefix=_optional_str(item.get("prefix")),
        disabled=bool(item.get("disabled")),
        requires_sign_in=bool(item.get("requires_sign_in")),
        quota_blocked=bool(item.get("quota_blocked")),
        status=_optional_str(item.get("status")),
    )


class CliproxyManagementClient:
    def __init__(self, *, settings: CliproxySettings, http_client: httpx.AsyncClient) -> None:
        self._base_url = f"{settings.url.rstrip('/')}{_API_PATH}"
        self._headers = {"Authorization": f"Bearer {settings.management_key}"}
        self._http_client = http_client

    async def _send(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, str] | None = None,
        json: Mapping[str, Any] | None = None,
    ) -> httpx.Response:
        """Ответ прокси; недоступность и ошибка сервера — `CliproxyUnavailableError`."""
        try:
            response = await self._http_client.request(
                method,
                f"{self._base_url}{path}",
                params=params,
                json=json,
                headers=self._headers,
            )
        except httpx.TransportError as exc:
            raise CliproxyUnavailableError(f"LLM-прокси недоступен: {exc}") from exc
        if classify_status(response.status_code) is HttpFailure.TRANSIENT:
            raise CliproxyUnavailableError(f"LLM-прокси вернул {response.status_code} для {path}")
        return response

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, str] | None = None,
        json: Mapping[str, Any] | None = None,
    ) -> Any:
        response = await self._send(method, path, params=params, json=json)
        status = response.status_code
        if classify_status(status) is not None:
            raise CliproxyRequestError(
                f"LLM-прокси отклонил {method} {path} ({status}): {_error_text(response)}",
                status_code=status,
            )
        return response.json() if response.content else {}

    async def oauth_auth_url(self, *, provider: str, credential: str | None = None) -> OAuthStart:
        """Ссылка входа; ``credential`` — повторный вход в уже привязанную учётку."""
        params = {"provider": provider}
        if credential is not None:
            params["name"] = credential
        data = await self._request("GET", "/oauth/auth-url", params=params)
        return OAuthStart(url=str(data["url"]), state=str(data["state"]))

    async def oauth_callback(self, *, provider: str, state: str, redirect_url: str) -> None:
        """Передаёт прокси адрес, на который браузер вернулся после входа."""
        await self._request(
            "POST",
            "/oauth/callback",
            json={"provider": provider, "state": state, "redirect_url": redirect_url},
        )

    async def oauth_status(self, state: str) -> OAuthStatus:
        """Итог входа; неизвестный или просроченный ``state`` прокси тоже отдаёт как `error`."""
        response = await self._send("GET", "/oauth/status", params={"state": state})
        data = _json_object(response)
        return OAuthStatus(
            state=OAuthState(str(data.get("status") or OAuthState.ERROR)),
            credential=_optional_str(data.get("auth_id")),
            error=_optional_str(data.get("error")),
        )

    async def oauth_cancel(self, state: str) -> None:
        await self._request("DELETE", "/oauth/session", params={"state": state})

    async def list_credentials(self) -> list[Credential]:
        data = await self._request("GET", "/credentials")
        return [_credential(item) for item in data.get("files") or [] if isinstance(item, dict)]

    async def credential_models(self, credential: str) -> list[str]:
        """Модели учётки — уже с её префиксом (`<префикс>/<модель>`)."""
        data = await self._request("GET", "/credentials/models", params={"name": credential})
        return [str(item["id"]) for item in data.get("models") or [] if isinstance(item, dict)]

    async def set_credential_prefix(self, credential: str, prefix: str) -> None:
        await self._request(
            "PATCH",
            "/credentials/fields",
            json={"name": credential, "prefix": prefix},
        )

    async def set_credential_disabled(self, credential: str, *, disabled: bool) -> None:
        await self._request(
            "PATCH",
            "/credentials/status",
            json={"name": credential, "disabled": disabled},
        )

    async def delete_credential(self, credential: str) -> None:
        await self._request("DELETE", "/credentials", params={"name": credential})

    async def refresh_credential(self, credential: str) -> None:
        await self._request("POST", "/credentials/refresh", json={"name": credential})

    async def reset_cooldown(self, auth_index: str) -> None:
        await self._request("POST", "/routing/cooldown/reset", json={"auth_index": auth_index})

    async def api_call(
        self,
        *,
        auth_index: str,
        method: str,
        url: str,
        headers: Mapping[str, str],
    ) -> ApiCallResult:
        """Запрос к провайдеру от имени учётки; `$TOKEN$` в заголовке прокси подставляет сам."""
        data = await self._request(
            "POST",
            "/requests/api-call",
            json={"auth_index": auth_index, "method": method, "url": url, "header": dict(headers)},
        )
        return ApiCallResult(status_code=int(data["status_code"]), body=str(data.get("body") or ""))

    async def latest_version(self) -> str:
        data = await self._request("GET", "/server/latest-version")
        return str(data[_LATEST_VERSION_FIELD])


def _json_object(response: httpx.Response) -> dict[str, Any]:
    try:
        data = response.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _error_text(response: httpx.Response) -> str:
    error = _json_object(response).get("error")
    return str(error) if error else response.text


@asynccontextmanager
async def open_cliproxy_client(
    settings: CliproxySettings | None = None,
) -> AsyncIterator[CliproxyManagementClient]:
    """Клиент на время операции, настройки — из окружения сервиса."""
    async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as http_client:
        yield CliproxyManagementClient(
            settings=settings or CliproxySettings.from_env(),
            http_client=http_client,
        )
