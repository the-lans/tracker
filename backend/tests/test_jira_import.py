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
from db.models.enums import TaskStatus
from db.models.tasks import Task
from services.errors import ExternalServiceError, NotFoundError
from services.jira_import import (
    attachment_copy_pending,
    issue_key_of_url,
    mark_attachment_copy_pending,
    save_description_html,
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


_DESCRIPTION_TEXT = "Пользователь не может войти после смены пароля"
_DESCRIPTION_HTML = "<p>Пользователь не может <b>войти</b> после смены пароля</p>"


def _issue_body(key: str = "PROJ-42") -> dict[str, Any]:
    return {
        "key": key,
        "fields": {
            "summary": "Починить вход",
            "description": _DESCRIPTION_TEXT,
            "attachment": [
                {"filename": "brief.md", "size": 5, "content": _ATTACHMENT_URL},
                {"filename": "brief.md", "size": 5, "content": _ATTACHMENT_URL},
                {"filename": "video.mp4", "size": 10**12, "content": _BIG_ATTACHMENT_URL},
                {"filename": "meta.txt", "size": 5, "content": _FOREIGN_ATTACHMENT_URL},
            ],
        },
        "renderedFields": {"description": _DESCRIPTION_HTML},
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
    await update_integrations(db_session, jira_url=server)
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
        """
        Сбой копирования не оставляет страницу задачи опрашивать артефакты вечно.
        """
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
        Одноимённые вложения сохраняются оба, слишком большое пропускается,
        ссылка на чужой хост запрашивается с сервера Jira и, не найдясь, тоже
        пропускается; повторный запуск ничего не добавляет.
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


class TestDescriptionHtml:
    async def test_client_reads_rendered_description(self) -> None:
        jira = FakeJira()
        async with jira.client() as http_client:
            issue = await _client(http_client).get_issue("PROJ-42")

        assert issue.description_html == _DESCRIPTION_HTML
        assert "expand=renderedFields" in jira.requested_urls[0]

    async def test_client_strips_edge_whitespace_of_description(self) -> None:
        def handle(_: httpx.Request) -> httpx.Response:
            body = _issue_body()
            body["fields"]["description"] = f"\n  {_DESCRIPTION_TEXT}  \n\n"
            return httpx.Response(200, json=body)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http_client:
            issue = await _client(http_client).get_issue("PROJ-42")

        assert issue.description == _DESCRIPTION_TEXT

    @pytest.mark.parametrize(
        "rendered",
        [None, {}, {"description": ""}, {"description": "  "}, {"description": 5}],
        ids=["absent", "empty_object", "empty", "blank", "not_text"],
    )
    async def test_client_without_rendered_description(self, rendered: object) -> None:
        def handle(_: httpx.Request) -> httpx.Response:
            body = _issue_body()
            body["renderedFields"] = rendered
            return httpx.Response(200, json=body)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http_client:
            issue = await _client(http_client).get_issue("PROJ-42")

        assert issue.description_html is None

    async def _task(self, authed_client: AsyncClient, description: str) -> dict[str, Any]:
        created = await authed_client.post(
            "/tasks",
            json={"code": "PROJ-42", "title": "t", "description": description},
        )
        assert created.status_code == 201, created.text
        body: dict[str, Any] = created.json()
        return body

    @pytest.mark.parametrize(
        ("description", "html", "saved"),
        [
            (_DESCRIPTION_TEXT, _DESCRIPTION_HTML, True),
            ("описание правили", _DESCRIPTION_HTML, False),
            (_DESCRIPTION_TEXT, None, False),
            (_DESCRIPTION_TEXT, "<p>" + "x" * 500_000 + "</p>", False),
        ],
        ids=["unchanged", "edited_meanwhile", "no_html", "too_large"],
    )
    async def test_saved_only_for_unchanged_description(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
        description: str,
        html: str | None,
        saved: bool,
    ) -> None:
        created = await self._task(authed_client, description)
        task = await db_session.get(Task, uuid.UUID(created["id"]))
        assert task is not None

        result = await save_description_html(
            db_session,
            task=task,
            description=_DESCRIPTION_TEXT,
            description_html=html,
        )
        await db_session.refresh(task)

        assert result is saved
        assert task.description_html == (html if saved else None)

    async def test_description_saved_before_trimming_still_gets_the_html(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        created = await self._task(authed_client, _DESCRIPTION_TEXT)
        task = await db_session.get(Task, uuid.UUID(created["id"]))
        assert task is not None
        # Описание, сохранённое до обрезки по краям, — в БД остаётся с пробелами.
        task.description = f"\n  {_DESCRIPTION_TEXT}  \n\n"
        await db_session.commit()

        result = await save_description_html(
            db_session,
            task=task,
            description=_DESCRIPTION_TEXT,
            description_html=_DESCRIPTION_HTML,
        )
        await db_session.refresh(task)

        assert result is True
        assert task.description_html == _DESCRIPTION_HTML

    async def test_background_copy_saves_html(
        self,
        authed_client: AsyncClient,
        current_user: User,
        db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        await _connect(authed_client, db_session)
        monkeypatch.setattr(
            jira_attachments.copy_jira_attachments_to_task, "delay", lambda *_: None
        )
        created = await authed_client.post(
            "/tasks",
            json={
                "code": "PROJ-42",
                "title": "t",
                "description": _DESCRIPTION_TEXT,
                "jira_issue_key": "PROJ-42",
            },
        )
        assert created.json()["description_html"] is None
        jira = FakeJira()

        @asynccontextmanager
        async def same_session() -> AsyncIterator[AsyncSession]:
            yield db_session

        monkeypatch.setattr(jira_attachments, "async_session_factory", same_session)
        monkeypatch.setattr(jira_attachments, "new_jira_http_client", jira.client)
        await jira_attachments.copy_jira_attachments_async(
            task_id=uuid.UUID(created.json()["id"]),
            user_id=current_user.id,
            key="PROJ-42",
        )

        task = await db_session.get(Task, uuid.UUID(created.json()["id"]))
        assert task is not None
        await db_session.refresh(task)
        assert task.description_html == _DESCRIPTION_HTML

    async def test_dropped_when_description_edited(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        created = await self._task(authed_client, _DESCRIPTION_TEXT)
        task = await db_session.get(Task, uuid.UUID(created["id"]))
        assert task is not None
        task.description_html = _DESCRIPTION_HTML
        await db_session.commit()

        unchanged = await authed_client.patch(
            f"/tasks/{created['id']}",
            json={"description": _DESCRIPTION_TEXT, "title": "new"},
        )
        edited = await authed_client.patch(
            f"/tasks/{created['id']}",
            json={"description": "другое описание"},
        )

        assert unchanged.json()["description_html"] == _DESCRIPTION_HTML
        assert edited.json()["description_html"] is None


class TestRefreshDescription:
    @staticmethod
    async def _imported_task(
        authed_client: AsyncClient,
        db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
        *,
        description: str = _DESCRIPTION_TEXT,
        key: str | None = "PROJ-42",
        queued: list[tuple[object, ...]] | None = None,
    ) -> str:
        await _connect(authed_client, db_session)
        delivered = [] if queued is None else queued
        monkeypatch.setattr(
            jira_attachments.copy_jira_attachments_to_task,
            "delay",
            lambda *args: delivered.append(args),
        )
        created = await authed_client.post(
            "/tasks",
            json={
                "code": "PROJ-42",
                "title": "t",
                "description": description,
                "jira_issue_key": key,
            },
        )
        assert created.status_code == 201, created.text
        delivered.clear()
        task_id: str = created.json()["id"]
        return task_id

    async def test_html_loaded_and_attachments_requeued(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
        fake_jira: FakeJira,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        queued: list[tuple[object, ...]] = []
        task_id = await self._imported_task(
            authed_client,
            db_session,
            monkeypatch,
            queued=queued,
        )

        response = await authed_client.post(f"/jira/tasks/{task_id}/description")

        assert response.status_code == 200, response.text
        assert response.json()["description_html"] == _DESCRIPTION_HTML
        assert fake_jira.requested_urls
        assert [args[2] for args in queued] == ["PROJ-42"]

    async def test_changed_description_is_replaced_with_the_one_from_jira(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
        fake_jira: FakeJira,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        del fake_jira
        task_id = await self._imported_task(
            authed_client,
            db_session,
            monkeypatch,
            description="Устаревшее описание",
        )

        response = await authed_client.post(f"/jira/tasks/{task_id}/description")

        assert response.status_code == 200, response.text
        assert response.json()["description"] == _DESCRIPTION_TEXT
        assert response.json()["description_html"] == _DESCRIPTION_HTML

    async def test_edge_whitespace_saved_before_trimming_is_not_a_change(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
        fake_jira: FakeJira,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        del fake_jira
        task_id = await self._imported_task(authed_client, db_session, monkeypatch)
        task = await db_session.get(Task, uuid.UUID(task_id))
        assert task is not None
        # Описание, сохранённое до обрезки по краям, у запущенной задачи.
        task.description = f"\n  {_DESCRIPTION_TEXT}\n\n"
        task.status = TaskStatus.IN_PROGRESS
        await db_session.commit()

        response = await authed_client.post(f"/jira/tasks/{task_id}/description")

        assert response.status_code == 200, response.text
        assert response.json()["description_html"] == _DESCRIPTION_HTML

    async def test_changed_description_of_a_started_task_is_not_replaced(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
        fake_jira: FakeJira,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        del fake_jira
        task_id = await self._imported_task(
            authed_client,
            db_session,
            monkeypatch,
            description="Устаревшее описание",
        )
        task = await db_session.get(Task, uuid.UUID(task_id))
        assert task is not None
        task.status = TaskStatus.IN_PROGRESS
        await db_session.commit()

        response = await authed_client.post(f"/jira/tasks/{task_id}/description")

        assert response.status_code == 409
        assert "только до запуска" in response.text
        await db_session.refresh(task)
        assert task.description == "Устаревшее описание"

    async def test_unchanged_text_of_a_started_task_still_gets_the_html(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
        fake_jira: FakeJira,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        del fake_jira
        task_id = await self._imported_task(authed_client, db_session, monkeypatch)
        task = await db_session.get(Task, uuid.UUID(task_id))
        assert task is not None
        task.status = TaskStatus.IN_PROGRESS
        await db_session.commit()

        response = await authed_client.post(f"/jira/tasks/{task_id}/description")

        assert response.status_code == 200, response.text
        assert response.json()["description_html"] == _DESCRIPTION_HTML

    async def test_conflict_without_a_jira_link(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
        fake_jira: FakeJira,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        del fake_jira
        task_id = await self._imported_task(authed_client, db_session, monkeypatch, key=None)

        response = await authed_client.post(f"/jira/tasks/{task_id}/description")

        assert response.status_code == 409
        assert "нет ссылки на задачу Jira" in response.text

    async def test_foreign_task_not_found(
        self,
        authed_client: AsyncClient,
        fake_jira: FakeJira,
    ) -> None:
        del fake_jira

        response = await authed_client.post(f"/jira/tasks/{uuid.uuid4()}/description")

        assert response.status_code == 404

    @pytest.mark.parametrize(
        ("url", "key"),
        [
            ("https://j.example.com/browse/proj-42", "PROJ-42"),
            ("https://j.example.com/browse/PROJ-7?focusedId=1", "PROJ-7"),
            ("https://j.example.com/projects/X", None),
            (None, None),
        ],
    )
    def test_issue_key_of_url(self, url: str | None, key: str | None) -> None:
        assert issue_key_of_url(url) == key
