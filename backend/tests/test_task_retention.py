"""
Сроки хранения данных архивной задачи (разделы 6.4, 14.3): история сессии —
через 180 дней в архиве, артефакты — через срок автора от завершения.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from db.models.enums import ParentSummaryStatus, TaskStatus
from db.models.tasks import Task, TaskParentSummary
from db.models.users import RETENTION_FOREVER, User
from db.queries.finished_tasks import FinishedTask
from services.distributed_lock import acquire_lock
from services.task_retention import (
    ARTIFACTS_LOCK_KEY,
    SESSIONS_LOCK_KEY,
    ArtifactsPass,
    SessionHistoryPass,
)
from tests.factories import make_task, make_user

if TYPE_CHECKING:
    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncSession

NOW = datetime(2026, 11, 14, 12, 0, tzinfo=UTC)


async def _author(db_session: AsyncSession, *, artifacts_retention_days: int = 90) -> User:
    user = await make_user(db_session)
    user.artifacts_retention_days = artifacts_retention_days
    await db_session.flush()
    return user


async def _archived(
    db_session: AsyncSession,
    *,
    author: User | None = None,
    status: TaskStatus = TaskStatus.ARCHIVED,
    archived_age: timedelta = timedelta(days=181),
    finished_age: timedelta = timedelta(days=200),
    **fields: Any,
) -> Task:
    author = author or await _author(db_session)
    return await make_task(
        db_session,
        created_by=author.id,
        status=status,
        archived_from_status=TaskStatus.DONE,
        finished_at=NOW - finished_age,
        archived_at=NOW - archived_age,
        **fields,
    )


_UNUSED_ROOT = Path("/unused")


async def _candidates(
    db_session: AsyncSession,
    pass_class: type[ArtifactsPass | SessionHistoryPass],
) -> set[uuid.UUID]:
    found = await pass_class(db_session, now=NOW, root=_UNUSED_ROOT).candidates()
    return {task.id for task in found}


def _task_dir(root: Path, task: Task) -> Path:
    directory = root / task.code / "projects"
    directory.mkdir(parents=True)
    (directory / "history.jsonl").write_text("{}")
    return root / task.code


async def _summary_running(
    db_session: AsyncSession,
    parent: Task,
    *,
    child_status: TaskStatus = TaskStatus.IN_PROGRESS,
) -> None:
    child = await make_task(db_session, status=child_status)
    db_session.add(
        TaskParentSummary(
            parent_task_id=parent.id,
            child_task_id=child.id,
            status=ParentSummaryStatus.PENDING,
        ),
    )
    await db_session.flush()


class TestFindSessionsToClean:
    @pytest.mark.parametrize(
        ("status", "archived_age", "cleaned", "expected"),
        [
            (TaskStatus.ARCHIVED, timedelta(days=181), False, True),
            (TaskStatus.ARCHIVED, timedelta(days=180, seconds=1), False, True),
            (TaskStatus.ARCHIVED, timedelta(days=180), False, False),
            (TaskStatus.ARCHIVED, timedelta(days=30), False, False),
            (TaskStatus.ARCHIVED, timedelta(days=400), True, False),
            (TaskStatus.DONE, timedelta(days=400), False, False),
            (TaskStatus.FAILED, timedelta(days=400), False, False),
        ],
        ids=["old", "just_over", "boundary", "recent", "already_cleaned", "done", "failed"],
    )
    async def test_threshold_status_and_mark(
        self,
        db_session: AsyncSession,
        status: TaskStatus,
        archived_age: timedelta,
        cleaned: bool,
        expected: bool,
    ) -> None:
        task = await _archived(
            db_session,
            status=status,
            archived_age=archived_age,
            session_cleaned_at=NOW if cleaned else None,
        )

        found = await _candidates(db_session, SessionHistoryPass)

        assert (task.id in found) is expected


class TestFindArtifactsToClean:
    @pytest.mark.parametrize(
        ("status", "finished_age", "days", "cleaned", "expected"),
        [
            (TaskStatus.ARCHIVED, timedelta(days=91), 90, False, True),
            (TaskStatus.ARCHIVED, timedelta(days=90, seconds=1), 90, False, True),
            (TaskStatus.ARCHIVED, timedelta(days=90), 90, False, False),
            (TaskStatus.ARCHIVED, timedelta(days=5), 3, False, True),
            (TaskStatus.ARCHIVED, timedelta(days=400), RETENTION_FOREVER, False, False),
            (TaskStatus.ARCHIVED, timedelta(days=400), 90, True, False),
            (TaskStatus.DONE, timedelta(days=400), 90, False, False),
            (TaskStatus.FAILED, timedelta(days=400), 90, False, False),
        ],
        ids=[
            "old",
            "just_over",
            "boundary",
            "author_term",
            "forever",
            "already_cleaned",
            "done",
            "failed",
        ],
    )
    async def test_threshold_status_and_mark(
        self,
        db_session: AsyncSession,
        status: TaskStatus,
        finished_age: timedelta,
        days: int,
        cleaned: bool,
        expected: bool,
    ) -> None:
        task = await _archived(
            db_session,
            author=await _author(db_session, artifacts_retention_days=days),
            status=status,
            finished_age=finished_age,
            artifacts_cleaned_at=NOW if cleaned else None,
        )

        found = await _candidates(db_session, ArtifactsPass)

        assert (task.id in found) is expected


class TestSessionsPass:
    async def test_removes_history_and_forgets_session(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        tmp_path: Path,
    ) -> None:
        task = await _archived(db_session, session_id=str(uuid.uuid4()))
        directory = _task_dir(tmp_path, task)
        kept = _task_dir(tmp_path, await _archived(db_session, archived_age=timedelta(days=1)))

        result = await SessionHistoryPass(db_session, now=NOW, root=tmp_path).run(redis_client)

        await db_session.refresh(task)
        assert result.done == [task.id]
        assert (directory.exists(), kept.exists()) == (False, True)
        assert (task.session_id, task.session_cleaned_at) == (None, NOW)
        assert task.context_cleared_at is not None

    async def test_summary_in_progress_skipped(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        tmp_path: Path,
    ) -> None:
        """
        Пересказ для дочерней задачи читает историю — удаление ждёт следующего часа.
        """
        session_id = str(uuid.uuid4())
        task = await _archived(db_session, session_id=session_id)
        await _summary_running(db_session, task)
        directory = _task_dir(tmp_path, task)
        await db_session.commit()

        result = await SessionHistoryPass(db_session, now=NOW, root=tmp_path).run(redis_client)

        await db_session.refresh(task)
        assert result.skipped == [task.id]
        assert directory.exists()
        assert (task.session_id, task.session_cleaned_at) == (session_id, None)

    async def test_stopped_child_summary_ignored(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        tmp_path: Path,
    ) -> None:
        """
        Запись `pending` у остановленной дочерней задачи пересказ уже не ждёт.
        """
        task = await _archived(db_session, session_id=str(uuid.uuid4()))
        await _summary_running(db_session, task, child_status=TaskStatus.FAILED)
        directory = _task_dir(tmp_path, task)
        await db_session.commit()

        result = await SessionHistoryPass(db_session, now=NOW, root=tmp_path).run(redis_client)

        assert result.done == [task.id]
        assert not directory.exists()

    async def test_left_archive_skipped(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """
        Задачу вернули в новые между выборкой и удалением — каталог не трогается.
        """
        task = await _archived(db_session)
        task_id = task.id
        directory = _task_dir(tmp_path, task)
        await db_session.commit()
        stale = await SessionHistoryPass(db_session, now=NOW, root=tmp_path).candidates()
        task.status = TaskStatus.NEW
        await db_session.commit()

        async def candidates(_self: SessionHistoryPass) -> list[FinishedTask]:
            return stale

        monkeypatch.setattr(SessionHistoryPass, "candidates", candidates)

        result = await SessionHistoryPass(db_session, now=NOW, root=tmp_path).run(redis_client)

        assert result.skipped == [task_id]
        assert directory.exists()

    async def test_lock_busy(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        tmp_path: Path,
    ) -> None:
        async with acquire_lock(redis_client, SESSIONS_LOCK_KEY, busy_message="занято"):
            result = await SessionHistoryPass(db_session, now=NOW, root=tmp_path).run(redis_client)

        assert result.lock_busy


class TestArtifactsPass:
    async def test_removes_artifacts(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        tmp_path: Path,
    ) -> None:
        session_id = str(uuid.uuid4())
        task = await _archived(db_session, session_id=session_id)
        directory = _task_dir(tmp_path, task)
        kept = _task_dir(tmp_path, await _archived(db_session, finished_age=timedelta(days=10)))

        result = await ArtifactsPass(db_session, now=NOW, root=tmp_path).run(redis_client)

        await db_session.refresh(task)
        assert result.done == [task.id]
        assert (directory.exists(), kept.exists()) == (False, True)
        assert (task.artifacts_cleaned_at, task.session_id) == (NOW, session_id)

    async def test_missing_directory_marked(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        tmp_path: Path,
    ) -> None:
        """
        Каталога нет (артефактов не было) — отметка ставится, проход не падает.
        """
        task = await _archived(db_session)

        result = await ArtifactsPass(db_session, now=NOW, root=tmp_path).run(redis_client)

        await db_session.refresh(task)
        assert result.done == [task.id]
        assert task.artifacts_cleaned_at == NOW

    async def test_summary_in_progress_skipped(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        tmp_path: Path,
    ) -> None:
        task = await _archived(db_session)
        await _summary_running(db_session, task)
        directory = _task_dir(tmp_path, task)
        await db_session.commit()

        result = await ArtifactsPass(db_session, now=NOW, root=tmp_path).run(redis_client)

        await db_session.refresh(task)
        assert result.skipped == [task.id]
        assert directory.exists()
        assert task.artifacts_cleaned_at is None

    async def test_lock_busy(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        tmp_path: Path,
    ) -> None:
        async with acquire_lock(redis_client, ARTIFACTS_LOCK_KEY, busy_message="занято"):
            result = await ArtifactsPass(db_session, now=NOW, root=tmp_path).run(redis_client)

        assert result.lock_busy
