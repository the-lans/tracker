"""Тесты `services/gitlab_sync.py` (этап 10 плана реализации).

`GitlabClient` подставляется через `httpx.MockTransport` (см.
`tests/test_gitlab_client.py`) — реального GitLab-инстанса не требуется.
Ребейз дочерних веток упражняется на локальных bare-репозиториях, тем же
способом, что и `tests/test_git_ops.py`.
"""

from __future__ import annotations

import uuid

import httpx
import pytest
import sqlalchemy as sa
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from clients.gitlab import GitlabClient
from db.models.enums import AppLogLevel, MergeStatus, RepositoryRole, TaskStatus, UserRole
from db.models.logs import AppLog
from db.models.repositories import Repository
from db.models.tasks import Task, TaskRepository
from db.models.users import User
from services import gitlab_sync as gitlab_sync_module
from services.crypto import encrypt
from services.gitlab_sync import (
    ACCESS_DENIED_KEY,
    find_merged_parents_with_children,
    permanent_failure_key,
    request_child_rebases_on_parent_merge,
    sync_merge_statuses,
    sync_task_repository_merge_status,
)
from services.notifications import NotificationEvent


def _make_repository(*, git_url: str = "git@gitlab.example.com:g/p.git") -> Repository:
    return Repository(name="r", git_url=git_url, deploy_key_encrypted=encrypt("k"))


async def _make_user(db_session: AsyncSession) -> User:
    user = User(email=f"{uuid.uuid4()}@example.com", role=UserRole.USER)
    db_session.add(user)
    await db_session.flush()
    return user


async def _make_task(
    db_session: AsyncSession,
    *,
    created_by: uuid.UUID,
    parent_task_id: uuid.UUID | None = None,
    status: TaskStatus = TaskStatus.IN_PROGRESS,
) -> Task:
    task = Task(
        code=f"RR-{uuid.uuid4().hex[:5]}",
        title="t",
        description="d",
        created_by=created_by,
        status=status,
        parent_task_id=parent_task_id,
    )
    db_session.add(task)
    await db_session.flush()
    return task


def _gitlab_client_returning(state: str | None) -> GitlabClient:
    payload = [{"state": state}] if state else []

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    return GitlabClient(
        base_url="https://gitlab.example.com",
        token="secret",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


async def test_sync_skips_not_pushed_repository(db_session: AsyncSession) -> None:
    user = await _make_user(db_session)
    task = await _make_task(db_session, created_by=user.id)
    repository = _make_repository()
    db_session.add(repository)
    await db_session.flush()
    task_repository = TaskRepository(
        task_id=task.id,
        repository_id=repository.id,
        role=RepositoryRole.READ_WRITE,
        branch_name="feature/RR-00001",
        base_branch="main",
        merge_status=MergeStatus.NOT_PUSHED,
    )
    db_session.add(task_repository)
    await db_session.flush()
    gitlab_client = _gitlab_client_returning("merged")

    result = await sync_task_repository_merge_status(
        db_session,
        task_repository=task_repository,
        repository=repository,
        gitlab_client=gitlab_client,
    )

    assert result is None
    assert task_repository.merge_status is MergeStatus.NOT_PUSHED


async def test_sync_updates_status_to_merged(db_session: AsyncSession) -> None:
    user = await _make_user(db_session)
    task = await _make_task(db_session, created_by=user.id)
    repository = _make_repository()
    db_session.add(repository)
    await db_session.flush()
    task_repository = TaskRepository(
        task_id=task.id,
        repository_id=repository.id,
        role=RepositoryRole.READ_WRITE,
        branch_name="feature/RR-00001",
        base_branch="main",
        merge_status=MergeStatus.PUSHED,
    )
    db_session.add(task_repository)
    await db_session.flush()
    gitlab_client = _gitlab_client_returning("merged")

    result = await sync_task_repository_merge_status(
        db_session,
        task_repository=task_repository,
        repository=repository,
        gitlab_client=gitlab_client,
    )

    assert result is MergeStatus.MERGED
    assert task_repository.merge_status is MergeStatus.MERGED


async def test_sync_ignores_closed_state_no_schema_mapping(db_session: AsyncSession) -> None:
    user = await _make_user(db_session)
    task = await _make_task(db_session, created_by=user.id)
    repository = _make_repository()
    db_session.add(repository)
    await db_session.flush()
    task_repository = TaskRepository(
        task_id=task.id,
        repository_id=repository.id,
        role=RepositoryRole.READ_WRITE,
        branch_name="feature/RR-00001",
        base_branch="main",
        merge_status=MergeStatus.PUSHED,
    )
    db_session.add(task_repository)
    await db_session.flush()
    gitlab_client = _gitlab_client_returning("closed")

    result = await sync_task_repository_merge_status(
        db_session,
        task_repository=task_repository,
        repository=repository,
        gitlab_client=gitlab_client,
    )

    assert result is None
    assert task_repository.merge_status is MergeStatus.PUSHED


async def test_sync_returns_none_when_no_merge_requests(db_session: AsyncSession) -> None:
    user = await _make_user(db_session)
    task = await _make_task(db_session, created_by=user.id)
    repository = _make_repository()
    db_session.add(repository)
    await db_session.flush()
    task_repository = TaskRepository(
        task_id=task.id,
        repository_id=repository.id,
        role=RepositoryRole.READ_WRITE,
        branch_name="feature/RR-00001",
        base_branch="main",
        merge_status=MergeStatus.PUSHED,
    )
    db_session.add(task_repository)
    await db_session.flush()
    gitlab_client = _gitlab_client_returning(None)

    result = await sync_task_repository_merge_status(
        db_session,
        task_repository=task_repository,
        repository=repository,
        gitlab_client=gitlab_client,
    )

    assert result is None


async def _parent_and_child(
    db_session: AsyncSession,
    *,
    parent_merge_status: MergeStatus,
    child_status: TaskStatus,
) -> tuple[TaskRepository, TaskRepository]:
    user = await _make_user(db_session)
    repository = _make_repository()
    db_session.add(repository)
    await db_session.flush()
    parent_task = await _make_task(db_session, created_by=user.id)
    child_task = await _make_task(
        db_session,
        created_by=user.id,
        parent_task_id=parent_task.id,
        status=child_status,
    )
    parent_task_repository = TaskRepository(
        task_id=parent_task.id,
        repository_id=repository.id,
        role=RepositoryRole.READ_WRITE,
        branch_name="feature/RR-parent",
        base_branch="main",
        merge_status=parent_merge_status,
    )
    child_task_repository = TaskRepository(
        task_id=child_task.id,
        repository_id=repository.id,
        role=RepositoryRole.READ_WRITE,
        branch_name="feature/RR-child",
        base_branch="feature/RR-parent",
    )
    db_session.add_all([parent_task_repository, child_task_repository])
    await db_session.flush()
    return parent_task_repository, child_task_repository


class TestRequestChildRebases:
    """Раздел 16.2: периодическая задача только отмечает ребейз, git не трогает."""

    async def test_skips_when_parent_not_merged(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
    ) -> None:
        parent, child = await _parent_and_child(
            db_session,
            parent_merge_status=MergeStatus.PUSHED,
            child_status=TaskStatus.IN_PROGRESS,
        )

        requested = await request_child_rebases_on_parent_merge(
            db_session,
            parent_task_repository=parent,
            redis_client=redis_client,
        )

        assert requested == []
        assert child.rebase_requested_at is None

    @pytest.mark.parametrize(
        ("child_status", "requested"),
        [
            (TaskStatus.IN_PROGRESS, True),
            (TaskStatus.PAUSED, True),
            (TaskStatus.PLAN_REVIEW, True),
            (TaskStatus.AWAITING_INPUT, True),
            # Решение 2026-10-19: done/failed не ребейзятся, new/queued склонируют свежую базу.
            (TaskStatus.NEW, False),
            (TaskStatus.QUEUED, False),
            (TaskStatus.DONE, False),
            (TaskStatus.FAILED, False),
        ],
    )
    async def test_marks_children_with_live_session(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        child_status: TaskStatus,
        requested: bool,
    ) -> None:
        parent, child = await _parent_and_child(
            db_session,
            parent_merge_status=MergeStatus.MERGED,
            child_status=child_status,
        )

        result = await request_child_rebases_on_parent_merge(
            db_session,
            parent_task_repository=parent,
            redis_client=redis_client,
        )

        assert (result == [child.task_id]) is requested
        assert (child.rebase_requested_at is not None) is requested
        assert child.base_branch == "main"


class TestSyncFailures:
    """Раздел 17.3: временный сбой не прерывает цикл, постоянный — уведомление без повторов."""

    async def _row(
        self,
        db_session: AsyncSession,
        *,
        branch: str,
    ) -> tuple[TaskRepository, Repository, Task]:
        user = await _make_user(db_session)
        task = await _make_task(db_session, created_by=user.id)
        repository = _make_repository(git_url=f"git@gitlab.example.com:g/{branch}.git")
        db_session.add(repository)
        await db_session.flush()
        task_repository = TaskRepository(
            task_id=task.id,
            repository_id=repository.id,
            role=RepositoryRole.READ_WRITE,
            branch_name=f"feature/{branch}",
            base_branch="main",
            merge_status=MergeStatus.PUSHED,
        )
        db_session.add(task_repository)
        await db_session.flush()
        return task_repository, repository, task

    def _client(self, status_by_project: dict[str, int]) -> tuple[GitlabClient, list[str]]:
        requested: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            project = next(name for name in status_by_project if name in str(request.url))
            requested.append(project)
            status = status_by_project[project]
            if status == httpx.codes.OK:
                return httpx.Response(status, json=[{"state": "merged"}])
            return httpx.Response(status, text="ошибка")

        client = GitlabClient(
            base_url="https://gitlab.example.com",
            token="secret",
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )
        return client, requested

    @pytest.fixture
    def pushes(self, monkeypatch: pytest.MonkeyPatch) -> list[tuple[NotificationEvent, uuid.UUID]]:
        sent: list[tuple[NotificationEvent, uuid.UUID]] = []

        async def record(
            _db: AsyncSession,
            *,
            event: NotificationEvent,
            task: Task,
            **_: object,
        ) -> None:
            sent.append((event, task.id))

        monkeypatch.setattr(gitlab_sync_module, "notify_task_event", record)
        return sent

    async def test_transient_keeps_loop(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        pushes: list[tuple[NotificationEvent, uuid.UUID]],
    ) -> None:
        broken = await self._row(db_session, branch="broken")
        healthy = await self._row(db_session, branch="healthy")
        client, _requested = self._client({"broken": 503, "healthy": 200})

        await sync_merge_statuses(
            db_session,
            rows=[broken, healthy],
            gitlab_client=client,
            redis_client=redis_client,
        )

        assert healthy[0].merge_status is MergeStatus.MERGED
        assert broken[0].merge_status is MergeStatus.PUSHED
        assert pushes == []
        assert not await redis_client.exists(permanent_failure_key(broken[0].id))

    async def test_permanent_notifies_once(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        pushes: list[tuple[NotificationEvent, uuid.UUID]],
    ) -> None:
        row = await self._row(db_session, branch="gone")
        client, requested = self._client({"gone": 404})

        for _ in range(2):
            await sync_merge_statuses(
                db_session,
                rows=[row],
                gitlab_client=client,
                redis_client=redis_client,
            )

        assert requested == ["gone"]
        assert pushes == [(NotificationEvent.GITLAB_SYNC_FAILED, row[2].id)]
        logs = (
            await db_session.execute(
                sa.select(AppLog).where(
                    AppLog.task_id == row[2].id,
                    AppLog.level == AppLogLevel.ERROR,
                ),
            )
        ).scalars().all()
        assert len(logs) == 1

    async def test_retries_after_pause_expires(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        pushes: list[tuple[NotificationEvent, uuid.UUID]],
    ) -> None:
        row = await self._row(db_session, branch="fixed")
        failing, _ = self._client({"fixed": 410})
        await sync_merge_statuses(
            db_session,
            rows=[row],
            gitlab_client=failing,
            redis_client=redis_client,
        )
        await redis_client.delete(permanent_failure_key(row[0].id))
        working, requested = self._client({"fixed": 200})

        await sync_merge_statuses(
            db_session,
            rows=[row],
            gitlab_client=working,
            redis_client=redis_client,
        )

        assert requested == ["fixed"]
        assert row[0].merge_status is MergeStatus.MERGED

    async def test_rejected_token(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        pushes: list[tuple[NotificationEvent, uuid.UUID]],
    ) -> None:
        """Токен один на систему: администратору — одна запись, авторам — ничего."""
        await redis_client.delete(ACCESS_DENIED_KEY)
        first = await self._row(db_session, branch="first")
        second = await self._row(db_session, branch="second")
        client, requested = self._client({"first": 401, "second": 401})
        try:
            for _ in range(2):
                await sync_merge_statuses(
                    db_session,
                    rows=[first, second],
                    gitlab_client=client,
                    redis_client=redis_client,
                )

            assert requested == ["first"]
            assert pushes == []
            assert await redis_client.exists(ACCESS_DENIED_KEY)
            assert not await redis_client.exists(permanent_failure_key(first[0].id))
            logs = (
                await db_session.execute(
                    sa.select(AppLog).where(
                        AppLog.source == "periodic.sync_gitlab_merge_status",
                        AppLog.message.contains("токен GitLab"),
                    ),
                )
            ).scalars().all()
            assert len(logs) == 1
        finally:
            await redis_client.delete(ACCESS_DENIED_KEY)


class TestFindMergedParentsWithChildren:
    """Раздел 16.2: проход ребейза берёт только слитые ветки, на которые ещё опираются дети."""

    async def test_only_pending_parents(self, db_session: AsyncSession) -> None:
        user = await _make_user(db_session)
        repository = _make_repository()
        db_session.add(repository)
        await db_session.flush()

        async def parent_branch(
            merge_status: MergeStatus,
            *,
            child_base: str | None,
        ) -> TaskRepository:
            parent = await _make_task(db_session, created_by=user.id, status=TaskStatus.DONE)
            branch = f"feature/{parent.code}"
            parent_repository = TaskRepository(
                task_id=parent.id,
                repository_id=repository.id,
                role=RepositoryRole.READ_WRITE,
                branch_name=branch,
                base_branch="main",
                merge_status=merge_status,
            )
            db_session.add(parent_repository)
            if child_base is not None:
                child = await _make_task(db_session, created_by=user.id, parent_task_id=parent.id)
                db_session.add(
                    TaskRepository(
                        task_id=child.id,
                        repository_id=repository.id,
                        role=RepositoryRole.READ_WRITE,
                        branch_name=f"feature/{child.code}",
                        base_branch=branch if child_base == "parent" else child_base,
                    ),
                )
            await db_session.flush()
            return parent_repository

        pending = await parent_branch(MergeStatus.MERGED, child_base="parent")
        already_switched = await parent_branch(MergeStatus.MERGED, child_base="main")
        without_children = await parent_branch(MergeStatus.MERGED, child_base=None)
        not_merged = await parent_branch(MergeStatus.PUSHED, child_base="parent")

        found = {row.id for row in await find_merged_parents_with_children(db_session)}

        assert pending.id in found
        assert not {already_switched.id, without_children.id, not_merged.id} & found
