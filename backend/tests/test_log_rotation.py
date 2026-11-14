"""Тесты `services/log_rotation.py` (раздел 16.2 ТЗ, `rotate_task_logs`)."""

from __future__ import annotations

import gzip
import json
import os
import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa

from db.models.enums import NodeLogStatus, NodeLogTriggerType, TaskStatus, UserRole
from db.models.logs import NodeLog
from db.models.tasks import Task
from db.models.users import User
from services import log_rotation
from services.log_rotation import prune_log_archive, rotate_node_logs

if TYPE_CHECKING:
    from pathlib import Path

    from sqlalchemy.ext.asyncio import AsyncSession

_NOW = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)
_OLD = _NOW - timedelta(days=100)
_RECENT = _NOW - timedelta(days=1)


async def _task_with_logs(
    db_session: AsyncSession,
    *,
    status: TaskStatus,
    started: list[datetime],
) -> Task:
    user = User(email=f"{uuid.uuid4()}@example.com", role=UserRole.USER)
    db_session.add(user)
    await db_session.flush()
    task = Task(
        code=f"RR-{uuid.uuid4().hex[:5]}",
        title="t",
        description="d",
        created_by=user.id,
        status=status,
    )
    db_session.add(task)
    await db_session.flush()
    db_session.add_all(
        [
            NodeLog(
                task_id=task.id,
                trigger_type=NodeLogTriggerType.PIPELINE,
                status=NodeLogStatus.SUCCESS,
                llm_output_text=f"ответ {index}",
                started_at=moment,
            )
            for index, moment in enumerate(started)
        ],
    )
    await db_session.flush()
    return task


async def _remaining(db_session: AsyncSession, task: Task) -> int:
    stmt = sa.select(sa.func.count()).select_from(NodeLog).where(NodeLog.task_id == task.id)
    return int((await db_session.execute(stmt)).scalar_one())


class TestRotateNodeLogs:
    async def test_archives_and_deletes_old_terminal_logs(
        self,
        db_session: AsyncSession,
        tmp_path: Path,
    ) -> None:
        done = await _task_with_logs(db_session, status=TaskStatus.DONE, started=[_OLD, _RECENT])
        running = await _task_with_logs(db_session, status=TaskStatus.IN_PROGRESS, started=[_OLD])
        # Из `failed` задачу перезапускают по её истории — она не ротируется.
        failed = await _task_with_logs(db_session, status=TaskStatus.FAILED, started=[_OLD])

        result = await rotate_node_logs(db_session, archive_root=tmp_path, now=_NOW)

        assert result.deleted_count == 1
        [archive] = result.archived_files
        assert archive.parent == tmp_path / done.code
        with gzip.open(archive, "rt", encoding="utf-8") as handle:
            records = [json.loads(line) for line in handle]
        assert [record["llm_output_text"] for record in records] == ["ответ 0"]
        assert records[0]["task_id"] == str(done.id)
        assert records[0]["status"] == "success"
        assert await _remaining(db_session, done) == 1
        assert await _remaining(db_session, running) == 1
        assert await _remaining(db_session, failed) == 1

    async def test_failed_write_keeps_history(
        self,
        db_session: AsyncSession,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        task = await _task_with_logs(db_session, status=TaskStatus.DONE, started=[_OLD])

        def disk_full(_path: Path, _records: object) -> None:
            raise OSError("No space left on device")

        monkeypatch.setattr(log_rotation, "_write_archive", disk_full)

        with pytest.raises(OSError, match="No space"):
            await rotate_node_logs(db_session, archive_root=tmp_path, now=_NOW)

        assert await _remaining(db_session, task) == 1
        assert list(tmp_path.iterdir()) == []

    async def test_repeat_run_is_noop(self, db_session: AsyncSession, tmp_path: Path) -> None:
        await _task_with_logs(db_session, status=TaskStatus.DONE, started=[_OLD])
        await rotate_node_logs(db_session, archive_root=tmp_path, now=_NOW)

        result = await rotate_node_logs(db_session, archive_root=tmp_path, now=_NOW)

        assert result.archived_files == []
        assert result.deleted_count == 0


def _archive_file(directory: Path, name: str, *, age: timedelta) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_bytes(b"")
    moment = (_NOW - age).timestamp()
    os.utime(path, (moment, moment))
    return path


class TestPruneLogArchive:
    @pytest.mark.parametrize(
        ("age", "kept"),
        [
            (timedelta(days=181), False),
            (timedelta(days=180, seconds=1), False),
            (timedelta(days=180), True),
            (timedelta(days=10), True),
        ],
        ids=["old", "just_over", "boundary", "recent"],
    )
    async def test_threshold(self, tmp_path: Path, age: timedelta, kept: bool) -> None:
        old = _archive_file(tmp_path / "RR-1", "node_logs-a.jsonl.gz", age=age)
        _archive_file(tmp_path / "RR-1", "node_logs-b.jsonl.gz", age=timedelta(days=1))

        await prune_log_archive(archive_root=tmp_path, now=_NOW)

        assert old.exists() is kept

    async def test_empty_task_dir_removed(self, tmp_path: Path) -> None:
        _archive_file(tmp_path / "RR-1", "node_logs-a.jsonl.gz", age=timedelta(days=400))

        removed = await prune_log_archive(archive_root=tmp_path, now=_NOW)

        assert removed == 1
        assert not (tmp_path / "RR-1").exists()

    async def test_foreign_files_and_links_kept(self, tmp_path: Path) -> None:
        """Удаляются только файлы архива: чужие имена и ссылки остаются."""
        old_age = timedelta(days=400)
        target = _archive_file(tmp_path / "outside", "node_logs-x.jsonl.gz", age=old_age)
        task_dir = tmp_path / "archive" / "RR-1"
        foreign = [
            _archive_file(task_dir, name, age=old_age)
            for name in ("notes.txt", "backup.jsonl.gz", "node_logs-a.json")
        ]
        link = task_dir / "node_logs-link.jsonl.gz"
        link.symlink_to(target)

        removed = await prune_log_archive(archive_root=tmp_path / "archive", now=_NOW)

        assert removed == 0
        assert all(path.exists() for path in foreign)
        assert (link.is_symlink(), target.exists()) == (True, True)

    async def test_missing_root(self, tmp_path: Path) -> None:
        assert await prune_log_archive(archive_root=tmp_path / "missing", now=_NOW) == 0
