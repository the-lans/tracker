"""
Архив задач в API (раздел 14.2, 15.1 ТЗ): `GET /tasks` без архивных задач и
раздел «Архив» — `GET /tasks/archive`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import pytest

from db.models.categories import TaskCategory
from db.models.enums import TaskStatus
from tests.factories import make_task, make_user

if TYPE_CHECKING:
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession

    from db.models.tasks import Task
    from db.models.users import User

FINISHED = datetime(2026, 3, 10, 12, tzinfo=UTC)
ARCHIVED = datetime(2026, 3, 24, 12, tzinfo=UTC)


async def _archived(db_session: AsyncSession, author: User, **fields: Any) -> Task:
    values: dict[str, Any] = {
        "status": TaskStatus.ARCHIVED,
        "archived_from_status": TaskStatus.FAILED,
        "finished_at": FINISHED,
        "archived_at": ARCHIVED,
    }
    values.update(fields)
    return await make_task(db_session, created_by=author.id, **values)


class TestTaskListWithoutArchive:
    async def test_archived_hidden(
        self,
        authed_client: AsyncClient,
        current_user: User,
        db_session: AsyncSession,
    ) -> None:
        done = await make_task(db_session, created_by=current_user.id, status=TaskStatus.DONE)
        await _archived(db_session, current_user)

        response = await authed_client.get("/tasks")

        assert [item["id"] for item in response.json()] == [str(done.id)]

    @pytest.mark.parametrize(
        "params",
        [{"include_archived": "true"}, {"status_filter": TaskStatus.ARCHIVED.value}],
        ids=["include_archived", "status_filter"],
    )
    async def test_archived_on_request(
        self,
        authed_client: AsyncClient,
        current_user: User,
        db_session: AsyncSession,
        params: dict[str, str],
    ) -> None:
        archived = await _archived(db_session, current_user)

        response = await authed_client.get("/tasks", params=params)

        assert str(archived.id) in [item["id"] for item in response.json()]

    async def test_archive_fields_in_task(
        self,
        authed_client: AsyncClient,
        current_user: User,
        db_session: AsyncSession,
    ) -> None:
        archived = await _archived(db_session, current_user, artifacts_cleaned_at=ARCHIVED)

        body = (await authed_client.get(f"/tasks/{archived.id}")).json()

        assert body["archived_from_status"] == TaskStatus.FAILED.value
        assert datetime.fromisoformat(body["artifacts_cleaned_at"]) == ARCHIVED
        assert body["session_cleaned_at"] is None
        assert datetime.fromisoformat(body["finished_at"]) == FINISHED
        assert datetime.fromisoformat(body["archived_at"]) == ARCHIVED


class TestArchiveEndpoint:
    async def test_row(
        self,
        authed_client: AsyncClient,
        current_user: User,
        db_session: AsyncSession,
    ) -> None:
        category = TaskCategory(name="Бэкенд", created_by=current_user.id)
        db_session.add(category)
        await db_session.flush()
        task = await _archived(db_session, current_user, title="Отчёт", category_id=category.id)

        response = await authed_client.get("/tasks/archive")

        assert response.status_code == 200
        body = response.json()
        assert (body["total"], body["page"], body["page_size"]) == (1, 1, 20)
        (row,) = body["items"]
        assert row["id"] == str(task.id)
        assert row["code"] == task.code
        assert row["title"] == "Отчёт"
        assert row["category_name"] == "Бэкенд"
        assert row["archived_from_status"] == TaskStatus.FAILED.value
        assert (row["repo_cleaned_at"], row["session_cleaned_at"], row["artifacts_cleaned_at"]) == (
            None,
            None,
            None,
        )
        assert row["created_by"] == str(current_user.id)

    async def test_foreign_hidden_for_user(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        await _archived(db_session, await make_user(db_session))

        body = (await authed_client.get("/tasks/archive")).json()

        assert (body["items"], body["total"]) == ([], 0)

    async def test_admin_sees_foreign(
        self,
        admin_client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        task = await _archived(db_session, await make_user(db_session))

        body = (await admin_client.get("/tasks/archive")).json()

        assert str(task.id) in [row["id"] for row in body["items"]]

    async def test_filters_and_page(
        self,
        authed_client: AsyncClient,
        current_user: User,
        db_session: AsyncSession,
    ) -> None:
        tasks = [
            await _archived(db_session, current_user, title=f"Отчёт {day}", finished_at=finished)
            for day, finished in enumerate(
                [FINISHED, FINISHED.replace(day=11), FINISHED.replace(day=12)],
            )
        ]
        await _archived(db_session, current_user, title="Другое", finished_at=FINISHED)

        response = await authed_client.get(
            "/tasks/archive",
            params={
                "search": "отчёт",
                "finished_from": FINISHED.isoformat(),
                "finished_to": FINISHED.replace(day=11).isoformat(),
                "page": 2,
                "page_size": 1,
            },
        )

        body = response.json()
        assert body["total"] == 2
        assert [row["id"] for row in body["items"]] == [str(tasks[0].id)]

    @pytest.mark.parametrize(
        "params",
        [
            {"page": 0},
            {"page_size": 0},
            {"page_size": 101},
            {"search": "x" * 201},
            {"finished_from": "not-a-date"},
            {
                "finished_from": FINISHED.isoformat(),
                "finished_to": FINISHED.replace(day=9).isoformat(),
            },
        ],
        ids=["page", "page_size_low", "page_size_high", "search_long", "date", "from_after_to"],
    )
    async def test_invalid_params(
        self,
        authed_client: AsyncClient,
        params: dict[str, Any],
    ) -> None:
        response = await authed_client.get("/tasks/archive", params=params)

        assert response.status_code == 422
