"""
Обёртка над Jira REST API v2 (раздел 15.6 ТЗ): чтение задачи по ключу и
скачивание её вложений от имени пользователя.

API v2 одинаков у Jira Cloud и Server/Data Center, а `description` в нём —
текст, а не документ Atlassian. Авторизация: с email — Basic (Jira Cloud,
email + API token), без email — Bearer (personal access token Server/DC).
Вложения запрашиваются только с сервера из настроек: из ссылки Jira берутся
путь и параметры, поэтому токен пользователя не уходит на другой хост, а
Base URL Jira, отличный от адреса в настройках, не мешает скачиванию.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit

import httpx

from clients.http_errors import HttpFailure, classify_status
from services.errors import ExternalServiceError, NotFoundError

_ISSUE_PATH = "/rest/api/2/issue/{key}"
_ISSUE_FIELDS = "summary,description,attachment"


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


def _on_server(url: str, *, server_url: str) -> str:
    """
    Ссылка Jira на сервере из настроек: Jira строит ссылки от своего Base URL,
    а он может отличаться от адреса, заданного администратором (внутренний
    адрес, явный порт).
    """
    link = urlsplit(url)
    server = urlsplit(server_url)
    return urlunsplit((server.scheme, server.netloc, link.path, link.query, ""))


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
        failure = classify_status(status)
        if failure is HttpFailure.TRANSIENT:
            message = f"Jira вернула {status} — повторите позже"
            raise ExternalServiceError(message, is_transient=True)
        if failure is HttpFailure.ACCESS_DENIED:
            message = f"Jira отклонила токен ({status}) — проверьте подключение в профиле"
            raise ExternalServiceError(message, is_transient=False)
        if failure is HttpFailure.CLIENT_ERROR:
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

    @staticmethod
    def _json_object(response: httpx.Response) -> dict[str, Any]:
        """
        Ответ API v2 — объект JSON; страница входа SSO или чужой сервер — нет.
        """
        try:
            body = response.json()
        except ValueError as exc:
            message = "Jira ответила не JSON — проверьте адрес Jira и личный токен"
            raise ExternalServiceError(message, is_transient=False) from exc
        if not isinstance(body, dict):
            message = "Jira вернула неожиданный ответ — проверьте адрес Jira"
            raise ExternalServiceError(message, is_transient=False)
        return body

    async def get_issue(self, key: str) -> JiraIssue:
        url = f"{self._base_url}{_ISSUE_PATH.format(key=quote(key, safe=''))}"
        response = await self._get(url, params={"fields": _ISSUE_FIELDS})
        self._raise_for_status(response, what=f"Задача {key}")
        body = self._json_object(response)
        fields = body.get("fields")
        if not isinstance(fields, dict):
            fields = {}
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
        response = await self._get(_on_server(attachment.content_url, server_url=self._base_url))
        self._raise_for_status(response, what=f"Вложение {attachment.filename}")
        if len(response.content) > max_bytes:
            raise AttachmentTooLargeError(attachment.filename)
        return response.content
