from pathlib import Path

import pytest

from services.errors import ValidationError
from services.knowledge_storage import (
    read_knowledge_content,
    store_knowledge_content,
    validate_knowledge_path,
)


class TestKnowledgeStorage:
    async def test_versions_are_immutable(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("TRACKER_KNOWLEDGE_ROOT", str(tmp_path))
        first = await store_knowledge_content(b"first")
        second = await store_knowledge_content(b"second")
        assert first != second
        assert await read_knowledge_content(first) == b"first"
        assert await read_knowledge_content(second) == b"second"

    @pytest.mark.parametrize(
        "path", ["", "/etc/passwd", "../secret", "a/../b", "a//b", "a\\b", "a\x00b"]
    )
    def test_invalid_paths(self, path: str) -> None:
        with pytest.raises(ValidationError):
            validate_knowledge_path(path)

    def test_nested_path(self) -> None:
        assert validate_knowledge_path("Документы/Карта.md") == "Документы/Карта.md"
