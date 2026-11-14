"""
Архив задач (раздел 14.2): уход в архив через N дней автора, очистка
репозиториев через M дней, выборка раздела «Архив» и поведение архивной задачи.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from db.models.enums import NodeLogStatus, NodeLogTriggerType, TaskStatus, UserRole
from db.models.logs import NodeLog
from db.models.tasks import Task
from db.models.users import RETENTION_FOREVER, User
from db.queries.finished_tasks import FinishedTask
from services.distributed_lock import acquire_lock
from services.errors import ConflictError, ValidationError
from services.maintenance_tasks import find_node_logs_eligible_for_rotation
from services.task_archive import (
    ARCHIVE_LOCK_KEY,
    CLEANUP_LOCK_KEY,
    ArchiveFilters,
    ArchivePass,
    RepositoryCleanupPass,
    list_archived_tasks,
)
from services.task_creation import TaskDraft
from services.task_duplication import duplicate_task
from services.task_editing import update_task
from services.task_env_variables import create_task_env_variable
from tests.factories import make_task, make_user

if TYPE_CHECKING:
    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncSession

NOW = datetime(2026, 11, 14, 12, 0, tzinfo=UTC)


async def _author(
    db_session: AsyncSession,
    *,
    archive_after_days: int = 14,
    cleanup_repos_after_days: int = 30,
    role: UserRole = UserRole.USER,
) -> User:
    user = await make_user(db_session, role=role)
    user.archive_after_days = archive_after_days
    user.cleanup_repos_after_days = cleanup_repos_after_days
    await db_session.flush()
    return user


async def _to_archive(db_session: AsyncSession) -> set[uuid.UUID]:
    return {task.id for task in await ArchivePass(db_session, now=NOW).candidates()}


def _cleanup(db_session: AsyncSession, repos_root: Path = Path("/unused")) -> RepositoryCleanupPass:
    return RepositoryCleanupPass(db_session, now=NOW, repos_root=repos_root)


async def _to_clean(db_session: AsyncSession) -> set[uuid.UUID]:
    return {task.id for task in await _cleanup(db_session).candidates()}


async def _finished_task(
    db_session: AsyncSession,
    author: User,
    *,
    status: TaskStatus = TaskStatus.DONE,
    age: timedelta,
    **fields: Any,
) -> Task:
    return await make_task(
        db_session,
        created_by=author.id,
        status=status,
        finished_at=NOW - age,
        **fields,
    )


class TestFindTasksToArchive:
    @pytest.mark.parametrize(
        ("status", "age", "expected"),
        [
            (TaskStatus.DONE, timedelta(days=15), True),
            (TaskStatus.FAILED, timedelta(days=15), True),
            (TaskStatus.DONE, timedelta(days=14, seconds=1), True),
            (TaskStatus.DONE, timedelta(days=14), False),
            (TaskStatus.DONE, timedelta(days=13), False),
            (TaskStatus.ARCHIVED, timedelta(days=40), False),
            (TaskStatus.IN_PROGRESS, timedelta(days=40), False),
            (TaskStatus.NEW, timedelta(days=40), False),
        ],
    )
    async def test_threshold_and_status(
        self,
        db_session: AsyncSession,
        status: TaskStatus,
        age: timedelta,
        expected: bool,
    ) -> None:
        task = await _finished_task(db_session, await _author(db_session), status=status, age=age)

        found = await _to_archive(db_session)

        assert (task.id in found) is expected

    async def test_disabled_for_author(self, db_session: AsyncSession) -> None:
        author = await _author(db_session, archive_after_days=RETENTION_FOREVER)
        task = await _finished_task(db_session, author, age=timedelta(days=400))

        found = await _to_archive(db_session)

        assert task.id not in found

    async def test_threshold_is_per_author(self, db_session: AsyncSession) -> None:
        patient = await _author(db_session, archive_after_days=30)
        hasty = await _author(db_session, archive_after_days=1)
        kept = await _finished_task(db_session, patient, age=timedelta(days=5))
        archived = await _finished_task(db_session, hasty, age=timedelta(days=5))

        found = await _to_archive(db_session)

        assert (kept.id in found, archived.id in found) == (False, True)


class TestArchivePass:
    @pytest.mark.parametrize("final_status", [TaskStatus.DONE, TaskStatus.FAILED])
    async def test_archives_with_final_status(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        final_status: TaskStatus,
    ) -> None:
        task = await _finished_task(
            db_session,
            await _author(db_session),
            status=final_status,
            age=timedelta(days=20),
        )
        finished_at = task.finished_at

        result = await ArchivePass(db_session, now=NOW).run(redis_client)

        await db_session.refresh(task)
        assert task.id in result.done
        assert (task.status, task.archived_from_status, task.archived_at, task.finished_at) == (
            TaskStatus.ARCHIVED,
            final_status,
            NOW,
            finished_at,
        )

    async def test_status_changed_meanwhile(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Задачу вернули в статус до запуска между выборкой и переходом — пропуск."""
        task = await _finished_task(db_session, await _author(db_session), age=timedelta(days=20))
        await db_session.commit()
        found = await ArchivePass(db_session, now=NOW).candidates()
        task.status = TaskStatus.NEW
        await db_session.commit()

        async def stale(_self: ArchivePass) -> list[FinishedTask]:
            return found

        monkeypatch.setattr(ArchivePass, "candidates", stale)

        result = await ArchivePass(db_session, now=NOW).run(redis_client)

        await db_session.refresh(task)
        assert task.id in result.skipped
        assert task.status is TaskStatus.NEW

    async def test_lock_busy(self, db_session: AsyncSession, redis_client: Redis) -> None:
        task = await _finished_task(db_session, await _author(db_session), age=timedelta(days=20))

        async with acquire_lock(redis_client, ARCHIVE_LOCK_KEY, busy_message="занято"):
            result = await ArchivePass(db_session, now=NOW).run(redis_client)

        assert result.lock_busy
        assert task.status is TaskStatus.DONE


class TestFindTasksToClean:
    @pytest.mark.parametrize(
        ("status", "age", "cleaned", "expected"),
        [
            (TaskStatus.DONE, timedelta(days=31), False, True),
            (TaskStatus.FAILED, timedelta(days=31), False, True),
            (TaskStatus.ARCHIVED, timedelta(days=31), False, True),
            (TaskStatus.DONE, timedelta(days=30), False, False),
            (TaskStatus.ARCHIVED, timedelta(days=31), True, False),
            (TaskStatus.IN_PROGRESS, timedelta(days=31), False, False),
        ],
    )
    async def test_threshold_status_and_mark(
        self,
        db_session: AsyncSession,
        status: TaskStatus,
        age: timedelta,
        cleaned: bool,
        expected: bool,
    ) -> None:
        task = await _finished_task(
            db_session,
            await _author(db_session),
            status=status,
            age=age,
            repo_cleaned_at=NOW if cleaned else None,
        )

        found = await _to_clean(db_session)

        assert (task.id in found) is expected

    async def test_disabled_for_author(self, db_session: AsyncSession) -> None:
        author = await _author(db_session, cleanup_repos_after_days=RETENTION_FOREVER)
        task = await _finished_task(db_session, author, age=timedelta(days=400))

        found = await _to_clean(db_session)

        assert task.id not in found


class TestCleanupPass:
    async def test_removes_task_directory(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        tmp_path: Path,
    ) -> None:
        task = await _finished_task(
            db_session,
            await _author(db_session),
            status=TaskStatus.ARCHIVED,
            age=timedelta(days=31),
        )
        root = tmp_path / task.code
        (root / "backend").mkdir(parents=True)

        result = await _cleanup(db_session, tmp_path).run(redis_client)

        await db_session.refresh(task)
        assert task.id in result.done
        assert not root.exists()
        assert task.repo_cleaned_at is not None

    async def test_busy_task_skipped(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Пересказ для дочерней задачи ещё идёт — очистка ждёт следующего часа."""
        task = await _finished_task(db_session, await _author(db_session), age=timedelta(days=31))
        await db_session.commit()

        async def busy(*_args: object, **_kwargs: object) -> None:
            raise ConflictError("пересказ")

        monkeypatch.setattr("services.task_archive.cleanup_task_repositories", busy)

        result = await _cleanup(db_session, tmp_path).run(redis_client)

        await db_session.refresh(task)
        assert task.id in result.skipped
        assert task.repo_cleaned_at is None

    async def test_lock_busy(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        tmp_path: Path,
    ) -> None:
        async with acquire_lock(redis_client, CLEANUP_LOCK_KEY, busy_message="занято"):
            result = await _cleanup(db_session, tmp_path).run(redis_client)

        assert result.lock_busy


class TestListArchivedTasks:
    async def _archived(self, db_session: AsyncSession, author: User, **fields: Any) -> Task:
        return await make_task(
            db_session,
            created_by=author.id,
            status=TaskStatus.ARCHIVED,
            archived_from_status=TaskStatus.DONE,
            **fields,
        )

    async def test_own_only_for_user(self, db_session: AsyncSession) -> None:
        author, other = await _author(db_session), await _author(db_session)
        own = await self._archived(db_session, author, finished_at=NOW)
        await self._archived(db_session, other, finished_at=NOW)
        await make_task(db_session, created_by=author.id, status=TaskStatus.DONE, finished_at=NOW)

        page = await list_archived_tasks(
            db_session,
            user=author,
            filters=ArchiveFilters(),
            page=1,
            page_size=20,
        )

        assert [row.task.id for row in page.rows] == [own.id]
        assert page.total == 1

    async def test_admin_sees_all(self, db_session: AsyncSession) -> None:
        admin = await _author(db_session, role=UserRole.ADMIN)
        tasks = [
            await self._archived(db_session, await _author(db_session), finished_at=NOW)
            for _ in range(2)
        ]

        page = await list_archived_tasks(
            db_session,
            user=admin,
            filters=ArchiveFilters(),
            page=1,
            page_size=100,
        )

        assert {task.id for task in tasks} <= {row.task.id for row in page.rows}

    @pytest.mark.parametrize(
        ("search", "expected"),
        [
            ("rr-arch", {"RR-ARCH-1", "RR-ARCH-2"}),
            ("платёж", {"RR-ARCH-2"}),
            ("100%", {"OTHER_100%"}),
            ("_", {"OTHER_100%"}),
            ("  ", {"RR-ARCH-1", "RR-ARCH-2", "OTHER_100%"}),
        ],
    )
    async def test_search_by_code_and_title(
        self,
        db_session: AsyncSession,
        search: str,
        expected: set[str],
    ) -> None:
        author = await _author(db_session)
        await self._archived(db_session, author, code="RR-ARCH-1", title="Поиск", finished_at=NOW)
        await self._archived(
            db_session,
            author,
            code="RR-ARCH-2",
            title="Платёжный шлюз",
            finished_at=NOW,
        )
        await self._archived(db_session, author, code="OTHER_100%", title="Другое", finished_at=NOW)

        page = await list_archived_tasks(
            db_session,
            user=author,
            filters=ArchiveFilters(search=search),
            page=1,
            page_size=20,
        )

        assert {row.task.code for row in page.rows} == expected

    async def test_period_and_order(self, db_session: AsyncSession) -> None:
        author = await _author(db_session)
        early, middle, late = [
            await self._archived(db_session, author, finished_at=NOW - timedelta(days=days))
            for days in (30, 10, 1)
        ]

        page = await list_archived_tasks(
            db_session,
            user=author,
            filters=ArchiveFilters(
                finished_from=NOW - timedelta(days=10),
                finished_to=NOW,
            ),
            page=1,
            page_size=20,
        )

        assert [row.task.id for row in page.rows] == [late.id, middle.id]
        assert early.id not in {row.task.id for row in page.rows}

    async def test_pages(self, db_session: AsyncSession) -> None:
        author = await _author(db_session)
        tasks = [
            await self._archived(db_session, author, finished_at=NOW - timedelta(hours=hours))
            for hours in range(5)
        ]

        second = await list_archived_tasks(
            db_session,
            user=author,
            filters=ArchiveFilters(),
            page=2,
            page_size=2,
        )

        assert [row.task.id for row in second.rows] == [tasks[2].id, tasks[3].id]
        assert second.total == 5

    async def test_reversed_period_rejected(self, db_session: AsyncSession) -> None:
        with pytest.raises(ValidationError):
            await list_archived_tasks(
                db_session,
                user=await _author(db_session),
                filters=ArchiveFilters(finished_from=NOW, finished_to=NOW - timedelta(days=1)),
                page=1,
                page_size=20,
            )


class TestArchivedTaskRules:
    """Архивная задача ведёт себя как выполненная: только просмотр, очистка, дублирование."""

    @pytest.mark.parametrize(
        ("archived_from", "allowed"),
        [(TaskStatus.DONE, True), (TaskStatus.FAILED, False)],
    )
    async def test_duplicate(
        self,
        db_session: AsyncSession,
        archived_from: TaskStatus,
        allowed: bool,
    ) -> None:
        author = await _author(db_session)
        source = await make_task(
            db_session,
            created_by=author.id,
            status=TaskStatus.ARCHIVED,
            archived_from_status=archived_from,
        )
        draft = TaskDraft(code="RR-COPY-1", title="t", description="d")

        if not allowed:
            with pytest.raises(ConflictError):
                await duplicate_task(db_session, source=source, draft=draft, created_by=author.id)
            return
        copy = await duplicate_task(db_session, source=source, draft=draft, created_by=author.id)
        assert copy.status is TaskStatus.NEW

    @pytest.mark.parametrize("status", [TaskStatus.DONE, TaskStatus.ARCHIVED])
    async def test_auto_accept_plan_locked(
        self,
        db_session: AsyncSession,
        status: TaskStatus,
    ) -> None:
        task = await make_task(db_session, status=status)

        with pytest.raises(ValidationError):
            await update_task(db_session, task=task, changes={"auto_accept_plan": True})

    @pytest.mark.parametrize("status", [TaskStatus.DONE, TaskStatus.ARCHIVED])
    async def test_env_variables_locked(
        self,
        db_session: AsyncSession,
        status: TaskStatus,
    ) -> None:
        task = await make_task(db_session, status=status)

        with pytest.raises(ConflictError):
            await create_task_env_variable(
                db_session,
                task=task,
                key="API_URL",
                value="x",
            )

    @pytest.mark.parametrize(
        ("status", "expected"),
        [(TaskStatus.DONE, True), (TaskStatus.ARCHIVED, True), (TaskStatus.FAILED, False)],
    )
    async def test_log_rotation(
        self,
        db_session: AsyncSession,
        status: TaskStatus,
        expected: bool,
    ) -> None:
        task = await make_task(db_session, status=status)
        node_log = NodeLog(
            task_id=task.id,
            trigger_type=NodeLogTriggerType.PIPELINE,
            status=NodeLogStatus.SUCCESS,
            started_at=NOW - timedelta(days=120),
        )
        db_session.add(node_log)
        await db_session.flush()

        eligible = await find_node_logs_eligible_for_rotation(
            db_session,
            now=NOW,
            threshold_days=90,
        )

        assert (node_log.id in eligible) is expected
