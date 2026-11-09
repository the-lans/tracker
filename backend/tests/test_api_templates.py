"""
Признак «загружен с диска» у файлов шаблона (`templates.uploaded_file_paths`,
разделы 3.1, 15.1 ТЗ).
"""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient

from services.errors import ValidationError
from services.template_files import resolve_uploaded_file_paths

_FILES = {"CLAUDE.md": "# Правила", ".claude/settings.json": "{}"}


async def _create(client: AsyncClient, **body: Any) -> dict[str, Any]:
    response = await client.post("/templates", json={"name": "Шаблон", "files": _FILES, **body})
    assert response.status_code == 201, response.text
    return dict(response.json())


class TestResolveUploadedFilePaths:
    @pytest.mark.parametrize(
        ("uploaded", "previous", "expected"),
        [
            (["CLAUDE.md"], (), ["CLAUDE.md"]),
            (["CLAUDE.md", "CLAUDE.md"], (), ["CLAUDE.md"]),
            ([], ["CLAUDE.md"], []),
            (None, ["CLAUDE.md", "gone.md"], ["CLAUDE.md"]),
            (None, (), []),
        ],
    )
    def test_resolved(
        self,
        uploaded: list[str] | None,
        previous: list[str],
        expected: list[str],
    ) -> None:
        assert resolve_uploaded_file_paths(_FILES, uploaded, previous=previous) == expected

    def test_unknown_path_rejected(self) -> None:
        with pytest.raises(ValidationError, match="gone.md"):
            resolve_uploaded_file_paths(_FILES, ["CLAUDE.md", "gone.md"])


class TestTemplateUploadedFilePaths:
    async def test_defaults_to_empty(self, authed_client: AsyncClient) -> None:
        created = await _create(authed_client)

        assert created["uploaded_file_paths"] == []

    async def test_saved_and_returned(self, authed_client: AsyncClient) -> None:
        created = await _create(authed_client, uploaded_file_paths=["CLAUDE.md"])

        fetched = await authed_client.get(f"/templates/{created['id']}")

        assert created["uploaded_file_paths"] == ["CLAUDE.md"]
        assert fetched.json()["uploaded_file_paths"] == ["CLAUDE.md"]

    @pytest.mark.parametrize("method", ["post", "patch"])
    async def test_unknown_path_rejected(self, authed_client: AsyncClient, method: str) -> None:
        body = {"name": "Шаблон", "files": _FILES, "uploaded_file_paths": ["gone.md"]}
        if method == "post":
            response = await authed_client.post("/templates", json=body)
        else:
            created = await _create(authed_client)
            response = await authed_client.patch(f"/templates/{created['id']}", json=body)

        assert response.status_code == 422
        assert "gone.md" in response.json()["error"]["message"]

    @pytest.mark.parametrize(
        ("patch", "expected"),
        [
            ({"uploaded_file_paths": [".claude/settings.json"]}, [".claude/settings.json"]),
            ({"files": {"CLAUDE.md": "новый текст"}}, ["CLAUDE.md"]),
            ({"files": {".claude/settings.json": "{}"}}, []),
            ({"name": "Другое имя"}, ["CLAUDE.md"]),
        ],
    )
    async def test_patch(
        self,
        authed_client: AsyncClient,
        patch: dict[str, Any],
        expected: list[str],
    ) -> None:
        created = await _create(authed_client, uploaded_file_paths=["CLAUDE.md"])

        response = await authed_client.patch(f"/templates/{created['id']}", json=patch)

        assert response.status_code == 200, response.text
        assert response.json()["uploaded_file_paths"] == expected
