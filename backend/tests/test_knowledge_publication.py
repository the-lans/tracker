import asyncio
import tracemalloc
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from db.queries import knowledge as queries
from db.session import engine
from services.knowledge_admin import collect_garbage
from services.knowledge_objects import KnowledgeProjection
from services.knowledge_storage import store_knowledge_content
from services.knowledge_views import _publish


class TestKnowledgePublication:
    async def test_bounded_memory_and_unchanged_inode(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("TRACKER_KNOWLEDGE_ROOT", str(tmp_path))
        key = await store_knowledge_content(bytes(1024 * 1024))
        files = [KnowledgeProjection(path=f"{index}.txt", storage_key=key) for index in range(64)]
        root = tmp_path / "view"
        tracemalloc.start()
        try:
            _publish(root, files)
            peak = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()
        assert peak < 1024 * 1024
        inode = (root / "0.txt").stat().st_ino
        before = (root / "0.txt").stat().st_mtime_ns
        _publish(root, files)
        assert (root / "0.txt").stat().st_ino == inode
        assert (root / "0.txt").stat().st_mtime_ns == before

    async def test_collection_waits_for_backup(
        self, db_session: AsyncSession, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("TRACKER_KNOWLEDGE_ROOT", str(tmp_path))
        async with engine.begin() as protection:
            await queries.protect_collection(protection)
            collector = asyncio.create_task(collect_garbage(db_session))
            await asyncio.sleep(0.05)
            assert not collector.done()
        assert await asyncio.wait_for(collector, timeout=5) == 0
