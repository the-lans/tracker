"""
`/tasks/{id}/artifacts` (раздел 14.3, 15.2, 19.2 ТЗ, решение №18 плана):
артефакты задачи видит и меняет её автор, `admin` — у любой задачи.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest

from db.models.tasks import Task
from tests.factories import make_user

if TYPE_CHECKING:
    from pathlib import Path

    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession

    from db.models.users import User


async def _task(db_session: AsyncSession, owner_id: uuid.UUID) -> Task:
    task = Task(code=f"RR-{uuid.uuid4().hex[:6]}", title="t", description="d", created_by=owner_id)
    db_session.add(task)
    await db_session.flush()
    return task


class TestCrud:
    async def test_upload_list_download_delete(
        self,
        authed_client: AsyncClient,
        current_user: User,
        db_session: AsyncSession,
        user_files_root: Path,
    ) -> None:
        task = await _task(db_session, current_user.id)
        base = f"/tasks/{task.id}/artifacts"

        uploaded = await authed_client.put(f"{base}/docs/spec.md", content=b"# spec")
        listed = await authed_client.get(base)
        downloaded = await authed_client.get(f"{base}/docs/spec.md")
        deleted = await authed_client.delete(f"{base}/docs/spec.md")

        assert uploaded.status_code == 201, uploaded.text
        assert uploaded.json()["path"] == "docs/spec.md"
        assert [item["path"] for item in listed.json()] == ["docs/spec.md"]
        assert downloaded.content == b"# spec"
        assert "attachment" in downloaded.headers["content-disposition"]
        assert deleted.status_code == 204
        assert not (user_files_root / task.code / "docs" / "spec.md").exists()

    async def test_too_large(
        self,
        authed_client: AsyncClient,
        current_user: User,
        db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr("api.tasks.max_upload_bytes", lambda: 4)
        task = await _task(db_session, current_user.id)

        response = await authed_client.put(f"/tasks/{task.id}/artifacts/a.bin", content=b"12345")

        assert response.status_code == 413

    async def test_escape_path(
        self,
        authed_client: AsyncClient,
        current_user: User,
        db_session: AsyncSession,
    ) -> None:
        task = await _task(db_session, current_user.id)

        url = f"/tasks/{task.id}/artifacts/a/..%2F..%2Fx"

        response = await authed_client.put(url, content=b"x")

        assert response.status_code == 422

    async def test_missing_file(
        self,
        authed_client: AsyncClient,
        current_user: User,
        db_session: AsyncSession,
    ) -> None:
        task = await _task(db_session, current_user.id)

        response = await authed_client.get(f"/tasks/{task.id}/artifacts/missing.txt")

        assert response.status_code == 404


class TestAccess:
    @pytest.mark.parametrize(
        ("method", "suffix"),
        [("get", ""), ("put", "/a.txt"), ("get", "/a.txt"), ("delete", "/a.txt")],
        ids=["list", "upload", "download", "delete"],
    )
    async def test_foreign_task_is_404(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
        method: str,
        suffix: str,
    ) -> None:
        other = await make_user(db_session)
        task = await _task(db_session, other.id)
        kwargs = {"content": b"x"} if method == "put" else {}
        url = f"/tasks/{task.id}/artifacts{suffix}"

        response = await getattr(authed_client, method)(url, **kwargs)

        assert response.status_code == 404

    async def test_admin_uploads_to_foreign_task(
        self,
        admin_client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        other = await make_user(db_session)
        task = await _task(db_session, other.id)

        response = await admin_client.put(f"/tasks/{task.id}/artifacts/a.txt", content=b"x")

        assert response.status_code == 201
