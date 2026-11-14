from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.knowledge import KnowledgeSection
from db.models.users import User


class TestKnowledgeApi:
    async def test_version_conflict_and_trash(
        self, admin_client: AsyncClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("TRACKER_KNOWLEDGE_ROOT", str(tmp_path))
        response = await admin_client.post(
            "/knowledge/sections", json={"name": "Общее", "user_read": True, "user_write": True}
        )
        assert response.status_code == 201, response.text
        section = response.json()["id"]
        endpoint = f"/knowledge/sections/{section}/entries"
        response = await admin_client.put(
            endpoint, json={"path": "Карта.md", "content": "one", "expected_version": 0}
        )
        assert response.status_code == 200, response.text
        entry = response.json()
        response = await admin_client.put(
            endpoint, json={"path": "Карта.md", "content": "two", "expected_version": 1}
        )
        assert response.status_code == 200
        response = await admin_client.put(
            endpoint, json={"path": "Карта.md", "content": "lost", "expected_version": 1}
        )
        assert response.status_code == 409
        response = await admin_client.get(
            f"/knowledge/entries/{entry['id']}/content", params={"version": 1}
        )
        assert response.json()["content"] == "one"
        response = await admin_client.patch(
            f"/knowledge/entries/{entry['id']}/deleted",
            json={"expected_version": 2, "deleted": True},
        )
        assert response.status_code == 200
        assert response.json()["deleted_at"] is not None

    async def test_users_cannot_create_sections(self, authed_client: AsyncClient) -> None:
        response = await authed_client.post("/knowledge/sections", json={"name": "Forbidden"})
        assert response.status_code == 403

    async def test_read_only_and_hidden(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
        current_user: User,
    ) -> None:
        hidden = KnowledgeSection(
            name="Hidden", created_by=current_user.id, user_read=False, user_write=False
        )
        readonly = KnowledgeSection(
            name="Read", created_by=current_user.id, user_read=True, user_write=False
        )
        db_session.add_all([hidden, readonly])
        await db_session.flush()
        visible = (await authed_client.get("/knowledge/sections")).json()
        assert [s["id"] for s in visible] == [str(readonly.id)]
        assert (
            await authed_client.get(f"/knowledge/sections/{hidden.id}/entries")
        ).status_code == 404
        response = await authed_client.put(
            f"/knowledge/sections/{readonly.id}/entries",
            json={"path": "x.md", "expected_version": 0},
        )
        assert response.status_code == 403

    async def test_move_folder_and_restore(
        self,
        admin_client: AsyncClient,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("TRACKER_KNOWLEDGE_ROOT", str(tmp_path))
        sections = []
        for name in ("Source", "Destination"):
            response = await admin_client.post("/knowledge/sections", json={"name": name})
            sections.append(response.json()["id"])
        folder = (
            await admin_client.put(
                f"/knowledge/sections/{sections[0]}/entries",
                json={"path": "folder", "is_directory": True, "expected_version": 0},
            )
        ).json()
        file = await admin_client.put(
            f"/knowledge/sections/{sections[0]}/entries",
            json={"path": "folder/map.md", "content": "map", "expected_version": 0},
        )
        assert file.status_code == 200, file.text
        response = await admin_client.patch(
            f"/knowledge/entries/{folder['id']}/location",
            json={"section_id": sections[1], "path": "moved", "expected_version": 1},
        )
        assert response.status_code == 200, response.text
        assert (tmp_path / "views" / sections[1] / "moved/map.md").read_text() == "map"
        assert not (tmp_path / "views" / sections[0] / "folder/map.md").exists()
        response = await admin_client.patch(
            f"/knowledge/entries/{folder['id']}/deleted",
            json={"expected_version": 2, "deleted": True},
        )
        assert response.status_code == 200, response.text
        assert not (tmp_path / "views" / sections[1] / "moved/map.md").exists()
        response = await admin_client.patch(
            f"/knowledge/entries/{folder['id']}/deleted",
            json={"expected_version": 3, "deleted": False},
        )
        assert response.status_code == 200, response.text
        assert (tmp_path / "views" / sections[1] / "moved/map.md").read_text() == "map"
