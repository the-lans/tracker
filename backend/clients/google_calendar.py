"""
Обёртка над Google OAuth 2.0 и Google Calendar API v3 (раздел 19.8 ТЗ):
вход по коду авторизации с доступом к календарю только на чтение, обновление
access-токена, список календарей и событий за период, отзыв доступа.

Отказ Google обновить токен (`invalid_grant`: доступ отозван, пароль сменён,
токен истёк) — `CalendarAuthRevokedError`: подключение нужно войти заново.
Адреса Google задаются `GoogleEndpoints` — стенд подменяет их моком.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from urllib.parse import quote, urlencode

import httpx

from clients.http_errors import HttpFailure, classify_status
from services.errors import ExternalServiceError

CALENDAR_SCOPES = ("openid", "email", "https://www.googleapis.com/auth/calendar.readonly")
_EVENTS_PAGE_SIZE = 250
_CANCELLED = "cancelled"
_INVALID_GRANT = "invalid_grant"
_JWT_PARTS = 3


@dataclass(frozen=True, slots=True)
class GoogleEndpoints:
    auth_url: str = "https://accounts.google.com/o/oauth2/v2/auth"
    token_url: str = "https://oauth2.googleapis.com/token"
    revoke_url: str = "https://oauth2.googleapis.com/revoke"
    calendar_api_url: str = "https://www.googleapis.com/calendar/v3"


@dataclass(frozen=True, slots=True)
class GoogleOAuthConfig:
    client_id: str
    client_secret: str
    redirect_uri: str


@dataclass(frozen=True, slots=True)
class GoogleTokens:
    access_token: str
    refresh_token: str | None
    email: str | None


@dataclass(frozen=True, slots=True)
class GoogleCalendarInfo:
    id: str
    summary: str
    primary: bool


@dataclass(frozen=True, slots=True)
class GoogleCalendarEvent:
    """
    Событие календаря: со временем (`starts_at`) или на весь день
    (`start_date`; `end_date` у Google исключающий).
    """

    id: str
    summary: str
    description: str | None
    starts_at: datetime | None
    ends_at: datetime | None
    start_date: date | None
    end_date: date | None


class CalendarAuthRevokedError(Exception):
    """Google больше не принимает refresh-токен: нужен повторный вход."""


class CalendarNotFoundError(ExternalServiceError):
    """Календаря нет или он больше не доступен аккаунту (удалён, отписались)."""


# Ответы Google, когда календарь удалён или аккаунт от него отписан.
_CALENDAR_GONE_STATUSES = frozenset({httpx.codes.NOT_FOUND, httpx.codes.GONE})


def _email_from_id_token(id_token: str | None) -> str | None:
    """
    Email из `id_token` ответа token-эндпоинта: токен получен напрямую от
    Google по TLS, поэтому подпись не проверяется (OpenID Connect Core, 3.1.3.7).
    """
    if not id_token:
        return None
    parts = id_token.split(".")
    if len(parts) != _JWT_PARTS:
        return None
    payload = parts[1] + "=" * (-len(parts[1]) % 4)
    try:
        claims = json.loads(base64.urlsafe_b64decode(payload))
    except (ValueError, json.JSONDecodeError):
        return None
    email = claims.get("email") if isinstance(claims, dict) else None
    return str(email) if email else None


def _parse_moment(value: Any) -> datetime | None:
    return datetime.fromisoformat(value) if isinstance(value, str) else None


def _parse_date(value: Any) -> date | None:
    return date.fromisoformat(value) if isinstance(value, str) else None


def _object(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _event(item: dict[str, Any]) -> GoogleCalendarEvent | None:
    start = _object(item.get("start"))
    end = _object(item.get("end"))
    event_id = item.get("id")
    if not event_id or item.get("status") == _CANCELLED:
        return None
    event = GoogleCalendarEvent(
        id=str(event_id),
        summary=str(item.get("summary") or "").strip(),
        description=str(item["description"]) if item.get("description") else None,
        starts_at=_parse_moment(start.get("dateTime")),
        ends_at=_parse_moment(end.get("dateTime")),
        start_date=_parse_date(start.get("date")),
        end_date=_parse_date(end.get("date")),
    )
    if event.starts_at is None and event.start_date is None:
        return None
    return event


class GoogleCalendarClient:
    def __init__(
        self,
        *,
        config: GoogleOAuthConfig,
        http_client: httpx.AsyncClient,
        endpoints: GoogleEndpoints | None = None,
    ) -> None:
        self._config = config
        self._http_client = http_client
        self._endpoints = endpoints or GoogleEndpoints()

    def authorization_url(self, *, state: str) -> str:
        """Ссылка входа: offline-доступ и согласие каждый раз — иначе нет refresh-токена."""
        query = urlencode(
            {
                "client_id": self._config.client_id,
                "redirect_uri": self._config.redirect_uri,
                "response_type": "code",
                "scope": " ".join(CALENDAR_SCOPES),
                "access_type": "offline",
                "prompt": "consent",
                "include_granted_scopes": "true",
                "state": state,
            },
        )
        return f"{self._endpoints.auth_url}?{query}"

    async def _request(
        self,
        method: str,
        url: str,
        **kwargs: Any,
    ) -> httpx.Response:
        try:
            return await self._http_client.request(method, url, **kwargs)
        except httpx.TransportError as exc:
            raise ExternalServiceError(f"Google недоступен: {exc}", is_transient=True) from exc

    @staticmethod
    def _json(response: httpx.Response) -> dict[str, Any]:
        try:
            body = response.json()
        except ValueError as exc:
            raise ExternalServiceError("Google ответил не JSON", is_transient=True) from exc
        if not isinstance(body, dict):
            raise ExternalServiceError("Google вернул неожиданный ответ", is_transient=False)
        return body

    def _raise_for_token_error(self, response: httpx.Response) -> None:
        if response.status_code < httpx.codes.BAD_REQUEST:
            return
        error = ""
        try:
            body = response.json()
            error = str(body.get("error", "")) if isinstance(body, dict) else ""
        except ValueError:
            error = ""
        if error == _INVALID_GRANT:
            raise CalendarAuthRevokedError(error)
        self._raise_for_status(response)

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        status = response.status_code
        if status in _CALENDAR_GONE_STATUSES:
            raise CalendarNotFoundError(
                f"Календарь недоступен в Google ({status})", is_transient=False
            )
        failure = classify_status(status)
        if failure is HttpFailure.TRANSIENT:
            message = f"Google вернул {status} — повторите позже"
            raise ExternalServiceError(message, is_transient=True)
        if failure is HttpFailure.ACCESS_DENIED:
            message = f"Google отклонил доступ к календарю ({status})"
            raise ExternalServiceError(message, is_transient=False)
        if failure is HttpFailure.CLIENT_ERROR:
            raise ExternalServiceError(f"Google вернул {status}", is_transient=False)

    async def _token_request(self, data: dict[str, str]) -> dict[str, Any]:
        response = await self._request(
            "POST",
            self._endpoints.token_url,
            data={
                "client_id": self._config.client_id,
                "client_secret": self._config.client_secret,
                **data,
            },
        )
        self._raise_for_token_error(response)
        return self._json(response)

    async def exchange_code(self, code: str) -> GoogleTokens:
        body = await self._token_request(
            {
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": self._config.redirect_uri,
            },
        )
        access_token = body.get("access_token")
        if not access_token:
            raise ExternalServiceError("Google не вернул access-токен", is_transient=False)
        refresh_token = body.get("refresh_token")
        return GoogleTokens(
            access_token=str(access_token),
            refresh_token=str(refresh_token) if refresh_token else None,
            email=_email_from_id_token(body.get("id_token")),
        )

    async def refresh_access_token(self, refresh_token: str) -> str:
        body = await self._token_request(
            {"refresh_token": refresh_token, "grant_type": "refresh_token"},
        )
        access_token = body.get("access_token")
        if not access_token:
            raise ExternalServiceError("Google не вернул access-токен", is_transient=False)
        return str(access_token)

    async def _get_json(
        self,
        path: str,
        *,
        access_token: str,
        params: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        response = await self._request(
            "GET",
            f"{self._endpoints.calendar_api_url}{path}",
            params=params,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        self._raise_for_status(response)
        return self._json(response)

    async def list_calendars(self, *, access_token: str) -> list[GoogleCalendarInfo]:
        body = await self._get_json("/users/me/calendarList", access_token=access_token)
        return [
            GoogleCalendarInfo(
                id=str(item["id"]),
                summary=str(item.get("summaryOverride") or item.get("summary") or item["id"]),
                primary=bool(item.get("primary")),
            )
            for item in body.get("items") or []
            if isinstance(item, dict) and item.get("id")
        ]

    async def list_events(
        self,
        *,
        access_token: str,
        calendar_id: str,
        time_min: datetime,
        time_max: datetime,
    ) -> list[GoogleCalendarEvent]:
        """
        События за `[time_min, time_max)`: повторяющиеся развёрнуты, отменённые —
        нет. Календаря больше нет у аккаунта — `CalendarNotFoundError`.
        """
        path = f"/calendars/{quote(calendar_id, safe='')}/events"
        params = {
            "timeMin": time_min.isoformat(),
            "timeMax": time_max.isoformat(),
            "singleEvents": "true",
            "orderBy": "startTime",
            "maxResults": str(_EVENTS_PAGE_SIZE),
        }
        events: list[GoogleCalendarEvent] = []
        while True:
            body = await self._get_json(path, access_token=access_token, params=params)
            for item in body.get("items") or []:
                event = _event(item) if isinstance(item, dict) else None
                if event is not None:
                    events.append(event)
            page_token = body.get("nextPageToken")
            if not page_token:
                return events
            params = {**params, "pageToken": str(page_token)}

    async def revoke(self, token: str) -> None:
        response = await self._request("POST", self._endpoints.revoke_url, data={"token": token})
        self._raise_for_status(response)
