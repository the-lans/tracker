"""
Регрессии ревью: публикация, очистка объектов и восстановление дерева.
"""

from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient

from services import knowledge_views


class TestKnowledgeRegressions:
    async def _section(self, client: AsyncClient, name: str = "Regression") -> str:
        response = await client.post("/knowledge/sections", json={"name": name})
        assert response.status_code == 201, response.text
        return str(response.json()["id"])

    async def _file(
        self, client: AsyncClient, section: str, path: str, **fields: object
    ) -> dict[str, Any]:
        response = await client.put(
            f"/knowledge/sections/{section}/entries",
            json={"path": path, "content": "original", "expected_version": 0, **fields},
        )
        assert response.status_code == 200, response.text
        body: dict[str, Any] = response.json()
        return body

    async def test_collapse_parent_path(
        self, admin_client: AsyncClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("TRACKER_KNOWLEDGE_ROOT", str(tmp_path))
        section = await self._section(admin_client)
        entry = await self._file(admin_client, section, "parent/file.txt")
        response = await admin_client.patch(
            f"/knowledge/entries/{entry['id']}/location",
            json={"section_id": section, "path": "parent", "expected_version": 1},
        )
        assert response.status_code == 200, response.text
        assert (tmp_path / "views" / section / "parent").read_text() == "original"
        assert (await admin_client.post("/knowledge/maintenance")).status_code == 200

    async def test_restore_child_restores_parent(
        self, admin_client: AsyncClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("TRACKER_KNOWLEDGE_ROOT", str(tmp_path))
        section = await self._section(admin_client)
        folder = await self._file(admin_client, section, "folder", is_directory=True)
        child = await self._file(admin_client, section, "folder/child.txt")
        sibling = await self._file(admin_client, section, "folder/sibling.txt")
        response = await admin_client.patch(
            f"/knowledge/entries/{folder['id']}/deleted",
            json={"expected_version": 1, "deleted": True},
        )
        assert response.status_code == 200
        response = await admin_client.patch(
            f"/knowledge/entries/{child['id']}/deleted",
            json={"expected_version": 2, "deleted": False},
        )
        assert response.status_code == 200, response.text
        response = await admin_client.put(
            f"/knowledge/sections/{section}/entries",
            json={"path": "folder/child.txt", "content": "edited", "expected_version": 3},
        )
        assert response.status_code == 200, response.text
        assert (tmp_path / "views" / section / "folder/child.txt").read_text() == "edited"
        entries = (await admin_client.get(f"/knowledge/sections/{section}/entries")).json()
        assert next(item for item in entries if item["id"] == sibling["id"])["deleted_at"]
        assert not (tmp_path / "views" / section / "folder/sibling.txt").exists()

    async def test_delete_reclaims_objects(
        self, admin_client: AsyncClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("TRACKER_KNOWLEDGE_ROOT", str(tmp_path))
        section = await self._section(admin_client)
        await self._file(admin_client, section, "file.txt")
        await self._file(admin_client, section, "file.txt", expected_version=1, content="updated")
        other = await self._section(admin_client, "Preserved")
        await self._file(admin_client, other, "keep.txt", content="keep")
        assert len(list((tmp_path / "objects").iterdir())) == 3
        response = await admin_client.delete(f"/knowledge/sections/{section}")
        assert response.status_code == 204, response.text
        assert len(list((tmp_path / "objects").iterdir())) == 1
        assert not (tmp_path / "views" / section).exists()
        assert (tmp_path / "views" / other / "keep.txt").read_text() == "keep"

    async def test_publication_failure_is_retryable(
        self, admin_client: AsyncClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("TRACKER_KNOWLEDGE_ROOT", str(tmp_path))
        section = await self._section(admin_client)
        original = knowledge_views._publish

        def fail(*_args: object) -> None:
            raise OSError("storage temporarily unavailable")

        monkeypatch.setattr(knowledge_views, "_publish", fail)
        entry = await self._file(admin_client, section, "file.txt")
        sections = (await admin_client.get("/knowledge/sections")).json()
        assert sections[0]["publication_pending"] is True
        response = await admin_client.get(f"/knowledge/entries/{entry['id']}/content")
        assert response.json()["content"] == "original"
        monkeypatch.setattr(knowledge_views, "_publish", original)
        response = await admin_client.post("/knowledge/maintenance")
        assert response.status_code == 200, response.text
        assert (tmp_path / "views" / section / "file.txt").read_text() == "original"
        assert (await admin_client.get("/knowledge/sections")).json()[0][
            "publication_pending"
        ] is False
