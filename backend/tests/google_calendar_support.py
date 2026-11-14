"""Фейк Google OAuth и Calendar API на `httpx.MockTransport` — для тестов раздела 19.8."""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, unquote

import httpx

from clients.google_calendar import GoogleCalendarClient, GoogleEndpoints, GoogleOAuthConfig

GOOGLE_EMAIL = "planner@example.com"
REFRESH_TOKEN = "refresh-token-secret"
ACCESS_TOKEN = "access-token"
CONFIG = GoogleOAuthConfig(
    client_id="client-id",
    client_secret="client-secret",
    redirect_uri="https://tracker.example.com/api/calendar/google/callback",
)
ENDPOINTS = GoogleEndpoints(
    auth_url="https://google.test/auth",
    token_url="https://google.test/token",
    revoke_url="https://google.test/revoke",
    calendar_api_url="https://google.test/calendar/v3",
)


def id_token(email: str) -> str:
    payload = base64.urlsafe_b64encode(json.dumps({"email": email}).encode()).decode().rstrip("=")
    return f"header.{payload}.signature"


@dataclass
class FakeGoogle:
    """Состояние фейка: события по календарям (страницами), отзыв доступа и запросы."""

    email: str = GOOGLE_EMAIL
    revoked: bool = False
    issue_refresh_token: bool = True
    events: dict[str, list[list[dict[str, Any]]]] = field(default_factory=dict)
    # Календари, удалённые в Google: их события — 404.
    missing: set[str] = field(default_factory=set)
    calendars: list[dict[str, Any]] = field(
        default_factory=lambda: [{"id": GOOGLE_EMAIL, "summary": "Основной", "primary": True}],
    )
    requests: list[httpx.Request] = field(default_factory=list)

    def _token(self, form: dict[str, list[str]]) -> httpx.Response:
        grant = form["grant_type"][0]
        if grant == "refresh_token" and self.revoked:
            return httpx.Response(400, json={"error": "invalid_grant"})
        body: dict[str, Any] = {"access_token": ACCESS_TOKEN}
        if grant == "authorization_code":
            body["id_token"] = id_token(self.email)
            if self.issue_refresh_token:
                body["refresh_token"] = REFRESH_TOKEN
        return httpx.Response(200, json=body)

    def _events(self, request: httpx.Request, calendar_id: str) -> httpx.Response:
        if calendar_id in self.missing:
            return httpx.Response(404, json={"error": {"code": 404}})
        pages = self.events.get(calendar_id, [[]])
        page = int(request.url.params.get("pageToken", "0"))
        body: dict[str, Any] = {"items": pages[page]}
        if page + 1 < len(pages):
            body["nextPageToken"] = str(page + 1)
        return httpx.Response(200, json=body)

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        url = str(request.url)
        if url == ENDPOINTS.token_url:
            return self._token(parse_qs(request.content.decode()))
        if url == ENDPOINTS.revoke_url:
            return httpx.Response(200)
        path = request.url.path.removeprefix("/calendar/v3")
        if path == "/users/me/calendarList":
            return httpx.Response(200, json={"items": self.calendars})
        if path.startswith("/calendars/") and path.endswith("/events"):
            calendar_id = unquote(path.removeprefix("/calendars/").removesuffix("/events"))
            return self._events(request, calendar_id)
        return httpx.Response(404)

    def client(self) -> GoogleCalendarClient:
        return GoogleCalendarClient(
            config=CONFIG,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(self.handle)),
            endpoints=ENDPOINTS,
        )
