"""
Импорт задачи из Jira (раздел 15.6 ТЗ, решение №20 плана). Jira подменена
транспортом httpx: проверяются запросы трекера и разбор ответов API v2.
"""

from __future__ import annotations

import base64
import uuid
from collections.abc import AsyncIterator, Iterator
from typing import TYPE_CHECKING, Any

import httpx
import pytest

from api.jira import get_jira_http_client
from clients.jira import JiraClient, JiraCredentials
from db.models.tasks import Task
from services.errors import ExternalServiceError, NotFoundError
from services.task_artifacts import list_artifacts

if TYPE_CHECKING:
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession

    from db.models.users import User

_JIRA_URL = "https://jira.example.com"
_ATTACHMENT_URL = f"{_JIRA_URL}/secure/attachment/1/brief.md"
_BIG_ATTACHMENT_URL = f"{_JIRA_URL}/secure/attachment/2/video.mp4"


def _issue_body(key: str = "PROJ-42") -> dict[str, Any]:
    return {
        "key": key,
        "fields": {
            "summary": "Починить вход",
            "description": "Пользователь не может войти после смены пароля",
            "attachment": [
                {"filename": "brief.md", "size": 5, "content": _ATTACHMENT_URL},
                {"filename": "video.mp4", "size": 10**12, "content": _BIG_ATTACHMENT_URL},
            ],
        },
    }


class FakeJira:
    """Jira, отвечающая на запросы трекера; запоминает заголовки авторизации."""

    def __init__(self, *, status: int = 200) -> None:
        self.status = status
        self.authorizations: list[str | None] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.authorizations.append(request.headers.get("Authorization"))
        if self.status != 200:
            return httpx.Response(self.status)
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


async def _connect(authed_client: AsyncClient, *, email: str | None = "me@example.com") -> None:
    response = await authed_client.put(
        "/profile/jira",
        json={"jira_url": _JIRA_URL, "jira_email": email, "jira_token": "jira-token"},
    )
    assert response.status_code == 200, response.text


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
            client = JiraClient(
                credentials=JiraCredentials(url=_JIRA_URL, email=email, token="t"),
                http_client=http_client,
            )
            issue = await client.get_issue("PROJ-42")

        assert jira.authorizations == [expected]
        assert issue.browse_url == f"{_JIRA_URL}/browse/PROJ-42"
        assert [attachment.filename for attachment in issue.attachments] == [
            "brief.md",
            "video.mp4",
        ]

    @pytest.mark.parametrize(
        ("status", "error"),
        [(404, NotFoundError), (401, ExternalServiceError), (503, ExternalServiceError)],
    )
    async def test_errors(self, status: int, error: type[Exception]) -> None:
        jira = FakeJira(status=status)
        async with jira.client() as http_client:
            client = JiraClient(
                credentials=JiraCredentials(url=_JIRA_URL, email=None, token="t"),
                http_client=http_client,
            )
            with pytest.raises(error):
                await client.get_issue("PROJ-42")


class TestProfileConnection:
    async def test_token_saved_not_returned(self, authed_client: AsyncClient) -> None:
        await _connect(authed_client)

        profile = (await authed_client.get("/profile")).json()

        assert profile["jira_url"] == _JIRA_URL
        assert profile["jira_token_set"] is True
        assert "jira-token" not in str(profile)
        assert "jira_token_encrypted" not in profile

    async def test_disconnect(self, authed_client: AsyncClient) -> None:
        await _connect(authed_client)

        response = await authed_client.delete("/profile/jira")

        assert response.json()["jira_token_set"] is False

    async def test_bad_url_rejected(self, authed_client: AsyncClient) -> None:
        response = await authed_client.put(
            "/profile/jira",
            json={"jira_url": "jira.example.com", "jira_token": "t"},
        )
        assert response.status_code == 422


class TestIssueDraft:
    async def test_fills_form(self, authed_client: AsyncClient, fake_jira: FakeJira) -> None:
        await _connect(authed_client)

        response = await authed_client.get("/jira/issues/proj-42")

        assert response.status_code == 200
        assert response.json() == {
            "code": "PROJ-42",
            "title": "Починить вход",
            "description": "Пользователь не может войти после смены пароля",
            "issue_url": f"{_JIRA_URL}/browse/PROJ-42",
            "attachments": [
                {"filename": "brief.md", "size": 5},
                {"filename": "video.mp4", "size": 10**12},
            ],
        }

    @pytest.mark.parametrize(
        ("prepare", "key", "status_code"),
        [
            (None, "PROJ-42", 422),
            ("connect", "not a key", 422),
            ("connect_missing", "PROJ-42", 404),
        ],
        ids=["not_connected", "bad_key", "not_found"],
    )
    async def test_errors(
        self,
        authed_client: AsyncClient,
        fake_jira: FakeJira,
        prepare: str | None,
        key: str,
        status_code: int,
    ) -> None:
        if prepare is not None:
            await _connect(authed_client)
        if prepare == "connect_missing":
            fake_jira.status = 404

        response = await authed_client.get(f"/jira/issues/{key}")

        assert response.status_code == status_code


class TestCreateFromJira:
    async def test_link_and_attachments(
        self,
        authed_client: AsyncClient,
        current_user: User,
        db_session: AsyncSession,
        fake_jira: FakeJira,
    ) -> None:
        await _connect(authed_client)

        response = await authed_client.post(
            "/tasks",
            json={
                "code": "PROJ-42",
                "title": "Починить вход",
                "description": "…",
                "jira_issue_key": "PROJ-42",
            },
        )

        assert response.status_code == 201, response.text
        assert response.json()["jira_issue_url"] == f"{_JIRA_URL}/browse/PROJ-42"
        task = await db_session.get(Task, uuid.UUID(response.json()["id"]))
        assert task is not None and task.created_by == current_user.id
        # Слишком большое вложение пропущено, задача создана.
        assert [artifact.path for artifact in list_artifacts(task.code)] == ["brief.md"]


