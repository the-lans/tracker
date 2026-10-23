"""
Обёртка над Jira REST API v2 (раздел 15.6 ТЗ): чтение задачи по ключу и
скачивание её вложений от имени пользователя.

API v2 одинаков у Jira Cloud и Server/Data Center, а `description` в нём —
текст, а не документ Atlassian. Авторизация: с email — Basic (Jira Cloud,
email + API token), без email — Bearer (personal access token Server/DC).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx

from services.errors import ExternalServiceError, NotFoundError

_ISSUE_PATH = "/rest/api/2/issue/{key}"
_ISSUE_FIELDS = "summary,description,attachment"
_SERVER_ERROR_THRESHOLD = 500
_CLIENT_ERROR_THRESHOLD = 400
_TRANSIENT_CLIENT_STATUSES = frozenset({httpx.codes.REQUEST_TIMEOUT, httpx.codes.TOO_MANY_REQUESTS})
_ACCESS_DENIED_STATUSES = frozenset({httpx.codes.UNAUTHORIZED, httpx.codes.FORBIDDEN})


@dataclass(frozen=True, slots=True)
class JiraCredentials:
    url: str
    email: str | None
    token: str


@dataclass(frozen=True, slots=True)
class JiraAttachment:
    filename: str
    size: int
    content_url: str


@dataclass(frozen=True, slots=True)
class JiraIssue:
    key: str
    summary: str
    description: str
    browse_url: str
    attachments: list[JiraAttachment]


class AttachmentTooLargeError(Exception):
    """Вложение больше допустимого размера артефакта (раздел 14.3)."""


def _attachments(fields: dict[str, Any]) -> list[JiraAttachment]:
    return [
        JiraAttachment(
            filename=str(item["filename"]),
            size=int(item.get("size") or 0),
            content_url=str(item["content"]),
        )
        for item in fields.get("attachment") or []
        if isinstance(item, dict) and item.get("filename") and item.get("content")
    ]


class JiraClient:
    def __init__(self, *, credentials: JiraCredentials, http_client: httpx.AsyncClient) -> None:
        self._base_url = credentials.url.rstrip("/")
        self._credentials = credentials
        self._http_client = http_client

    def _auth_headers(self) -> dict[str, str]:
        if self._credentials.email:
            return {}
        return {"Authorization": f"Bearer {self._credentials.token}"}

    def _auth(self) -> httpx.BasicAuth | None:
        if not self._credentials.email:
            return None
        return httpx.BasicAuth(self._credentials.email, self._credentials.token)

    def _raise_for_status(self, response: httpx.Response, *, what: str) -> None:
        status = response.status_code
        if status == httpx.codes.NOT_FOUND:
            raise NotFoundError(f"{what} не найдена в Jira")
        if status >= _SERVER_ERROR_THRESHOLD or status in _TRANSIENT_CLIENT_STATUSES:
            message = f"Jira вернула {status} — повторите позже"
            raise ExternalServiceError(message, is_transient=True)
        if status in _ACCESS_DENIED_STATUSES:
            message = f"Jira отклонила токен ({status}) — проверьте подключение в профиле"
            raise ExternalServiceError(message, is_transient=False)
        if status >= _CLIENT_ERROR_THRESHOLD:
            raise ExternalServiceError(f"Jira вернула {status}: {what}", is_transient=False)

    async def _get(self, url: str, *, params: dict[str, str] | None = None) -> httpx.Response:
        try:
            return await self._http_client.get(
                url,
                params=params,
                headers=self._auth_headers(),
                auth=self._auth() or httpx.USE_CLIENT_DEFAULT,
                follow_redirects=True,
            )
        except httpx.TransportError as exc:
            raise ExternalServiceError(f"Jira недоступна: {exc}", is_transient=True) from exc

    async def get_issue(self, key: str) -> JiraIssue:
        url = f"{self._base_url}{_ISSUE_PATH.format(key=quote(key, safe=''))}"
        response = await self._get(url, params={"fields": _ISSUE_FIELDS})
        self._raise_for_status(response, what=f"Задача {key}")
        body = response.json()
        fields: dict[str, Any] = body.get("fields") or {}
        issue_key = str(body.get("key") or key)
        return JiraIssue(
            key=issue_key,
            summary=str(fields.get("summary") or ""),
            description=str(fields.get("description") or ""),
            browse_url=f"{self._base_url}/browse/{issue_key}",
            attachments=_attachments(fields),
        )

    async def download_attachment(self, attachment: JiraAttachment, *, max_bytes: int) -> bytes:
        """Содержимое вложения; больше ``max_bytes`` — `AttachmentTooLargeError`."""
        if attachment.size > max_bytes:
            raise AttachmentTooLargeError(attachment.filename)
        response = await self._get(attachment.content_url)
        self._raise_for_status(response, what=f"Вложение {attachment.filename}")
        if len(response.content) > max_bytes:
            raise AttachmentTooLargeError(attachment.filename)
        return response.content
