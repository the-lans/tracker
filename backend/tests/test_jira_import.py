"""
Импорт задачи из Jira (раздел 15.6 ТЗ, решение №20 плана). Jira подменена
транспортом httpx: проверяются запросы трекера и разбор ответов API v2.
Адрес Jira задаёт администратор, личный токен — пользователь в профиле.
"""

from __future__ import annotations

import base64
import uuid
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

import httpx
import pytest

from api.jira import get_jira_http_client
from clients.jira import JiraAttachment, JiraClient, JiraCredentials
from db.models.tasks import Task
from services.errors import ExternalServiceError, NotFoundError
from services.jira_import import (
    attachment_copy_pending,
    mark_attachment_copy_pending,
    unique_artifact_name,
)
from services.system_settings import update_integrations
from services.task_artifacts import list_artifacts
from tasks import jira_attachments

if TYPE_CHECKING:
    from httpx import AsyncClient
    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncSession

    from db.models.users import User

_JIRA_URL = "https://jira.example.com"
_ATTACHMENT_URL = f"{_JIRA_URL}/secure/attachment/1/brief.md"
_BIG_ATTACHMENT_URL = f"{_JIRA_URL}/secure/attachment/2/video.mp4"
# Base URL Jira отличается от адреса в настройках: путь тот же, хост другой.
_BASE_URL_ATTACHMENT_URL = "http://jira.internal:8080/secure/attachment/1/brief.md"
_FOREIGN_ATTACHMENT_URL = "http://169.254.169.254/latest/meta-data/"


def _issue_body(key: str = "PROJ-42") -> dict[str, Any]:
    return {
        "key": key,
        "fields": {
            "summary": "Починить вход",
            "description": "Пользователь не может войти после смены пароля",
            "attachment": [
                {"filename": "brief.md", "size": 5, "content": _ATTACHMENT_URL},
                {"filename": "brief.md", "size": 5, "content": _ATTACHMENT_URL},
                {"filename": "video.mp4", "size": 10**12, "content": _BIG_ATTACHMENT_URL},
                {"filename": "meta.txt", "size": 5, "content": _FOREIGN_ATTACHMENT_URL},
            ],
        },
    }


class FakeJira:
    """Jira, отвечающая на запросы трекера; запоминает заголовки авторизации."""

    def __init__(self, *, status: int = 200) -> None:
        self.status = status
        self.html_instead_of_json = False
        self.authorizations: list[str | None] = []
        self.requested_urls: list[str] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.authorizations.append(request.headers.get("Authorization"))
        self.requested_urls.append(str(request.url))
        if self.status != 200:
            return httpx.Response(self.status)
        if self.html_instead_of_json:
            return httpx.Response(200, text="<html>Вход через SSO</html>")
        if request.url.path.startswith("/rest/api/2/issue/"):
            key = request.url.path.rsplit("/", 1)[-1]
            return httpx.Response(200, json=_issue_body(key))
        if str(request.url) == _ATTACHMENT_URL:
            return httpx.Response(200, content=b"brief")
        return httpx.Response(404)

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handle))


@pytest.fixture
def fake_jira() -> Iterator[FakeJira]:
    from main import app

    jira = FakeJira()

    async def client() -> AsyncIterator[httpx.AsyncClient]:
        async with jira.client() as http_client:
            yield http_client

    app.dependency_overrides[get_jira_http_client] = client
    yield jira
    app.dependency_overrides.pop(get_jira_http_client, None)


async def _connect(
    authed_client: AsyncClient,
    db_session: AsyncSession,
    *,
    email: str | None = "me@example.com",
    server: str | None = _JIRA_URL,
) -> None:
    """Администратор задал адрес Jira, пользователь сохранил личный токен."""
    await update_integrations(db_session, gitlab_url=None, gitlab_token=None, jira_url=server)
    response = await authed_client.put(
        "/profile/jira",
        json={"jira_email": email, "jira_token": "jira-token"},
    )
    assert response.status_code == 200, response.text


def _client(http_client: httpx.AsyncClient, *, email: str | None = None) -> JiraClient:
    return JiraClient(
        credentials=JiraCredentials(url=_JIRA_URL, email=email, token="t"),
        http_client=http_client,
    )


class TestClient:
    @pytest.mark.parametrize(
        ("email", "expected"),
        [
            ("me@example.com", "Basic " + base64.b64encode(b"me@example.com:t").decode()),
            (None, "Bearer t"),
        ],
        ids=["cloud", "server"],
    )
    async def test_auth_header(self, email: str | None, expected: str) -> None:
        jira = FakeJira()
        async with jira.client() as http_client:
            issue = await _client(http_client, email=email).get_issue("PROJ-42")

        assert jira.authorizations == [expected]
        assert issue.browse_url == f"{_JIRA_URL}/browse/PROJ-42"
        assert [attachment.filename for attachment in issue.attachments] == [
            "brief.md",
            "brief.md",
            "video.mp4",
            "meta.txt",
        ]

    @pytest.mark.parametrize(
        ("status", "error"),
        [(404, NotFoundError), (401, ExternalServiceError), (503, ExternalServiceError)],
    )
    async def test_errors(self, status: int, error: type[Exception]) -> None:
        jira = FakeJira(status=status)
        async with jira.client() as http_client:
            with pytest.raises(error):
                await _client(http_client).get_issue("PROJ-42")

    async def test_html_instead_of_json(self) -> None:
        """Страница входа SSO с кодом 200 — понятная ошибка, а не 500."""
        jira = FakeJira()
        jira.html_instead_of_json = True
        async with jira.client() as http_client:
            with pytest.raises(ExternalServiceError, match="не JSON"):
                await _client(http_client).get_issue("PROJ-42")

    async def test_attachment_from_settings_server(self) -> None:
        """Ссылка с другим хостом запрашивается с сервера из настроек."""
        jira = FakeJira()
        attachment = JiraAttachment(
            filename="brief.md",
            size=5,
            content_url=_BASE_URL_ATTACHMENT_URL,
        )
        async with jira.client() as http_client:
            content = await _client(http_client).download_attachment(attachment, max_bytes=100)

        assert content == b"brief"
        assert jira.requested_urls == [_ATTACHMENT_URL]


class TestUniqueArtifactName:
    def test_same_names_get_suffix(self) -> None:
        taken: set[str] = set()

        names = [unique_artifact_name(name, taken) for name in ["image.png"] * 3 + ["notes"]]

        assert names == ["image.png", "image (2).png", "image (3).png", "notes"]


class TestProfileConnection:
    async def test_token_saved_not_returned(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        await _connect(authed_client, db_session)

        profile = (await authed_client.get("/profile")).json()

        assert profile["jira_email"] == "me@example.com"
        assert profile["jira_token_set"] is True
        assert "jira-token" not in str(profile)
        assert "jira_token_encrypted" not in profile

    async def test_disconnect(self, authed_client: AsyncClient, db_session: AsyncSession) -> None:
        await _connect(authed_client, db_session)

        response = await authed_client.delete("/profile/jira")

        assert response.json()["jira_token_set"] is False

    async def test_server_set_by_admin(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        await _connect(authed_client, db_session)

        response = await authed_client.get("/jira/server")

        assert response.json() == {"jira_url": _JIRA_URL}


class TestIssueDraft:
    async def test_fills_form(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
        fake_jira: FakeJira,
    ) -> None:
        await _connect(authed_client, db_session)

        response = await authed_client.get("/jira/issues/proj-42")

        assert response.status_code == 200
        assert response.json() == {
            "code": "PROJ-42",
            "title": "Починить вход",
            "description": "Пользователь не может войти после смены пароля",
            "issue_url": f"{_JIRA_URL}/browse/PROJ-42",
            "attachments": [
                {"filename": "brief.md", "size": 5},
                {"filename": "brief.md", "size": 5},
                {"filename": "video.mp4", "size": 10**12},
                {"filename": "meta.txt", "size": 5},
            ],
        }

    @pytest.mark.parametrize(
        ("prepare", "key", "status_code"),
        [
            (None, "PROJ-42", 422),
            ("no_server", "PROJ-42", 422),
            ("connect", "not a key", 422),
            ("connect_missing", "PROJ-42", 404),
            ("connect_html", "PROJ-42", 502),
        ],
        ids=["not_connected", "no_server", "bad_key", "not_found", "not_json"],
    )
    async def test_errors(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
        fake_jira: FakeJira,
        prepare: str | None,
        key: str,
        status_code: int,
    ) -> None:
        if prepare is not None:
            await _connect(
                authed_client,
                db_session,
                server=None if prepare == "no_server" else _JIRA_URL,
            )
        fake_jira.status = 404 if prepare == "connect_missing" else 200
        fake_jira.html_instead_of_json = prepare == "connect_html"

        response = await authed_client.get(f"/jira/issues/{key}")

        assert response.status_code == status_code


class TestCreateFromJira:
    @pytest.mark.usefixtures("redis_client")
    async def test_attachments_queued(
        self,
        authed_client: AsyncClient,
        current_user: User,
        db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        await _connect(authed_client, db_session)
        queued: list[tuple[str, ...]] = []
        monkeypatch.setattr(
            jira_attachments.copy_jira_attachments_to_task,
            "delay",
            lambda *args: queued.append(args),
        )

        response = await authed_client.post(
            "/tasks",
            json={
                "code": "PROJ-42",
                "title": "Починить вход",
                "description": "…",
                "jira_issue_key": "proj-42",
            },
        )

        assert response.status_code == 201, response.text
        assert response.json()["jira_issue_url"] == f"{_JIRA_URL}/browse/PROJ-42"
        assert queued == [(response.json()["id"], str(current_user.id), "PROJ-42")]
        copy = await authed_client.get(f"/tasks/{response.json()['id']}/jira-attachments")
        assert copy.json() == {"pending": True}

    @pytest.mark.usefixtures("redis_client")
    async def test_not_pending_without_jira(self, authed_client: AsyncClient) -> None:
        created = await authed_client.post(
            "/tasks",
            json={"code": "RR-1", "title": "t", "description": "d"},
        )

        response = await authed_client.get(f"/tasks/{created.json()['id']}/jira-attachments")

        assert response.json() == {"pending": False}

    async def test_pending_cleared_after_failure(
        self,
        redis_client: Redis,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Сбой копирования не оставляет страницу задачи опрашивать артефакты вечно."""
        task_id = uuid.uuid4()
        await mark_attachment_copy_pending(redis_client, task_id)

        async def broken_copy(**_: object) -> None:
            raise RuntimeError("worker crashed")

        monkeypatch.setattr(jira_attachments, "_copy", broken_copy)
        with pytest.raises(RuntimeError):
            await jira_attachments.copy_jira_attachments_async(
                task_id=task_id,
                user_id=uuid.uuid4(),
                key="PROJ-42",
            )

        assert not await attachment_copy_pending(redis_client, task_id)

    async def test_background_copy(
        self,
        redis_client: Redis,
        authed_client: AsyncClient,
        current_user: User,
        db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """
        Одноимённые вложения сохраняются оба, слишком большое и лежащее не на
        сервере Jira — пропускаются; повторный запуск ничего не добавляет.
        """
        await _connect(authed_client, db_session)
        task_queue = jira_attachments.copy_jira_attachments_to_task
        monkeypatch.setattr(task_queue, "delay", lambda *_: None)
        created = await authed_client.post(
            "/tasks",
            json={"code": "PROJ-42", "title": "t", "description": "d", "jira_issue_key": "PROJ-42"},
        )
        jira = FakeJira()

        @asynccontextmanager
        async def same_session() -> AsyncIterator[AsyncSession]:
            yield db_session

        monkeypatch.setattr(jira_attachments, "async_session_factory", same_session)
        monkeypatch.setattr(jira_attachments, "new_jira_http_client", jira.client)
        for _ in range(2):
            await jira_attachments.copy_jira_attachments_async(
                task_id=uuid.UUID(created.json()["id"]),
                user_id=current_user.id,
                key="PROJ-42",
            )

        task = await db_session.get(Task, uuid.UUID(created.json()["id"]))
        assert task is not None
        assert [artifact.path for artifact in list_artifacts(task.code)] == [
            "brief (2).md",
            "brief.md",
        ]
        assert all(url.startswith(_JIRA_URL) for url in jira.requested_urls)
        assert not await attachment_copy_pending(redis_client, task.id)
