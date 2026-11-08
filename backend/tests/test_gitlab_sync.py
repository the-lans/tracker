"""Тесты `services/gitlab_sync.py` (этап 10 плана реализации).

`GitlabClient` подставляется через `httpx.MockTransport` (см.
`tests/test_gitlab_client.py`) — реального GitLab-инстанса не требуется.
Ребейз дочерних веток упражняется на локальных bare-репозиториях, тем же
способом, что и `tests/test_git_ops.py`.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable

import httpx
import pytest
import sqlalchemy as sa
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from clients.gitlab import GitlabClient
from db.models.enums import AppLogLevel, MergeStatus, RepositoryRole, TaskStatus
from db.models.logs import AppLog
from db.models.repositories import GitCredential, Repository
from db.models.tasks import Task, TaskRepository
from services import gitlab_sync as gitlab_sync_module
from services.crypto import encrypt
from services.git_credentials import GitlabApiAccess
from services.gitlab_sync import (
    access_denied_key,
    find_merged_parents_with_children,
    permanent_failure_key,
    request_child_rebases_on_parent_merge,
    sync_merge_statuses,
    sync_task_repository_merge_status,
)
from services.notifications import NotificationEvent
from tests.factories import build_git_credential, build_repository, make_task, make_user


def _make_repository(*, git_url: str = "git@gitlab.example.com:g/p.git") -> Repository:
    return build_repository(name="r", git_url=git_url)




async def _make_task(
    db_session: AsyncSession,
    *,
    created_by: uuid.UUID,
    parent_task_id: uuid.UUID | None = None,
    status: TaskStatus = TaskStatus.IN_PROGRESS,
) -> Task:
    return await make_task(
        db_session,
        created_by=created_by,
        status=status,
        parent_task_id=parent_task_id,
    )


def _gitlab_client_returning(state: str | None) -> GitlabClient:
    payload = [{"state": state}] if state else []

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    return GitlabClient(
        base_url="https://gitlab.example.com",
        token="secret",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


class TestSyncMergeStatus:
    """Раздел 16.2: статус слияния подтягивается только у запушенных веток."""

    @pytest.mark.parametrize(
        ("merge_status", "gitlab_state", "result", "stored"),
        [
            (MergeStatus.NOT_PUSHED, "merged", None, MergeStatus.NOT_PUSHED),
            (MergeStatus.PUSHED, "merged", MergeStatus.MERGED, MergeStatus.MERGED),
            (MergeStatus.PUSHED, "closed", None, MergeStatus.PUSHED),
            (MergeStatus.PUSHED, None, None, MergeStatus.PUSHED),
        ],
        ids=["not_pushed", "merged", "closed", "no_merge_requests"],
    )
    async def test_sync(
        self,
        db_session: AsyncSession,
        merge_status: MergeStatus,
        gitlab_state: str | None,
        result: MergeStatus | None,
        stored: MergeStatus,
    ) -> None:
        user = await make_user(db_session)
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
            merge_status=merge_status,
        )
        db_session.add(task_repository)
        await db_session.flush()

        synced = await sync_task_repository_merge_status(
            db_session,
            task_repository=task_repository,
            repository=repository,
            gitlab_client=_gitlab_client_returning(gitlab_state),
        )

        assert synced is result
        assert task_repository.merge_status is stored


async def _parent_and_child(
    db_session: AsyncSession,
    *,
    parent_merge_status: MergeStatus,
    child_status: TaskStatus,
) -> tuple[TaskRepository, TaskRepository]:
    user = await make_user(db_session)
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

    @pytest.fixture
    async def credential(self, db_session: AsyncSession) -> GitCredential:
        return await self._credential(db_session, name="Основной", token="main")

    @staticmethod
    async def _credential(
        db_session: AsyncSession,
        *,
        name: str,
        token: str = "api",
        **overrides: object,
    ) -> GitCredential:
        values: dict[str, object] = {
            "name": name,
            "kind": "ssh_key",
            "host": "gitlab.example.com",
            "gitlab_api_enabled": True,
            "gitlab_api_token_encrypted": encrypt(token),
        }
        row = build_git_credential(**(values | overrides))
        db_session.add(row)
        await db_session.flush()
        return row

    async def _row(
        self,
        db_session: AsyncSession,
        *,
        branch: str,
        credential: GitCredential | None,
    ) -> tuple[TaskRepository, Repository, Task]:
        user = await make_user(db_session)
        task = await _make_task(db_session, created_by=user.id)
        repository = _make_repository(git_url=f"git@gitlab.example.com:g/{branch}.git")
        repository.git_credential = credential
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

    @staticmethod
    def _client_for(
        status_by_project: dict[str, int],
    ) -> tuple[Callable[[GitlabApiAccess], GitlabClient], list[str], list[GitlabApiAccess]]:
        requested: list[str] = []
        accesses: list[GitlabApiAccess] = []

        def handler(request: httpx.Request) -> httpx.Response:
            project = next(name for name in status_by_project if name in str(request.url))
            requested.append(project)
            status = status_by_project[project]
            if status == httpx.codes.OK:
                return httpx.Response(status, json=[{"state": "merged"}])
            return httpx.Response(status, text="ошибка")

        def client_for(access: GitlabApiAccess) -> GitlabClient:
            accesses.append(access)
            return GitlabClient(
                base_url=access.base_url,
                token=access.token,
                http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
            )

        return client_for, requested, accesses

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
        credential: GitCredential,
        pushes: list[tuple[NotificationEvent, uuid.UUID]],
    ) -> None:
        broken = await self._row(db_session, branch="broken", credential=credential)
        healthy = await self._row(db_session, branch="healthy", credential=credential)
        client_for, _requested, _ = self._client_for({"broken": 503, "healthy": 200})

        await sync_merge_statuses(
            db_session,
            rows=[broken, healthy],
            client_for=client_for,
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
        credential: GitCredential,
        pushes: list[tuple[NotificationEvent, uuid.UUID]],
    ) -> None:
        row = await self._row(db_session, branch="gone", credential=credential)
        client_for, requested, _ = self._client_for({"gone": 404})

        for _ in range(2):
            await sync_merge_statuses(
                db_session,
                rows=[row],
                client_for=client_for,
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
        credential: GitCredential,
        pushes: list[tuple[NotificationEvent, uuid.UUID]],
    ) -> None:
        row = await self._row(db_session, branch="fixed", credential=credential)
        failing, _, _ = self._client_for({"fixed": 410})
        await sync_merge_statuses(
            db_session,
            rows=[row],
            client_for=failing,
            redis_client=redis_client,
        )
        await redis_client.delete(permanent_failure_key(row[0].id))
        working, requested, _ = self._client_for({"fixed": 200})

        await sync_merge_statuses(
            db_session,
            rows=[row],
            client_for=working,
            redis_client=redis_client,
        )

        assert requested == ["fixed"]
        assert row[0].merge_status is MergeStatus.MERGED

    async def test_rejected_token_pauses_only_its_credential(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        credential: GitCredential,
        pushes: list[tuple[NotificationEvent, uuid.UUID]],
    ) -> None:
        """Отказ токена: администратору — одна запись, авторам — ничего, другие доступы работают."""
        other = await self._credential(db_session, name="Партнёр", token="partner")
        first = await self._row(db_session, branch="first", credential=credential)
        second = await self._row(db_session, branch="second", credential=credential)
        healthy = await self._row(db_session, branch="healthy", credential=other)
        client_for, requested, _ = self._client_for({"first": 401, "second": 401, "healthy": 200})
        try:
            for _ in range(2):
                await sync_merge_statuses(
                    db_session,
                    rows=[first, second, healthy],
                    client_for=client_for,
                    redis_client=redis_client,
                )

            assert sorted(requested) == ["first", "healthy", "healthy"]
            assert healthy[0].merge_status is MergeStatus.MERGED
            assert pushes == []
            assert await redis_client.exists(access_denied_key(credential.id))
            assert not await redis_client.exists(access_denied_key(other.id))
            assert not await redis_client.exists(permanent_failure_key(first[0].id))
            logs = (
                await db_session.execute(
                    sa.select(AppLog).where(
                        AppLog.source == "periodic.sync_gitlab_merge_status",
                        AppLog.message.contains("токен GitLab API"),
                    ),
                )
            ).scalars().all()
            assert [log.context for log in logs] == [{"git_credential_id": str(credential.id)}]
            assert "«Основной»" in logs[0].message
        finally:
            await redis_client.delete(access_denied_key(credential.id))

    @pytest.mark.parametrize(
        "overrides",
        [
            pytest.param(None, id="без учётных данных"),
            pytest.param({"gitlab_api_enabled": False}, id="API выключен"),
        ],
    )
    async def test_skips_without_api(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        overrides: dict[str, object] | None,
    ) -> None:
        credential = (
            None
            if overrides is None
            else await self._credential(db_session, name="Без API", token="off", **overrides)
        )
        row = await self._row(db_session, branch="skipped", credential=credential)
        client_for, requested, accesses = self._client_for({"skipped": 200})

        await sync_merge_statuses(
            db_session,
            rows=[row],
            client_for=client_for,
            redis_client=redis_client,
        )

        assert requested == [] and accesses == []
        assert row[0].merge_status is MergeStatus.PUSHED

    async def test_client_per_credential(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        credential: GitCredential,
    ) -> None:
        other = await self._credential(
            db_session,
            name="Свой адрес",
            token="custom",
            gitlab_api_url="https://gitlab.example.com:8443/gl",
        )
        rows = [
            await self._row(db_session, branch="a", credential=credential),
            await self._row(db_session, branch="b", credential=other),
            await self._row(db_session, branch="c", credential=credential),
        ]
        client_for, _, accesses = self._client_for({"a": 200, "b": 200, "c": 200})

        await sync_merge_statuses(
            db_session,
            rows=rows,
            client_for=client_for,
            redis_client=redis_client,
        )

        assert sorted(accesses, key=lambda access: access.token) == [
            GitlabApiAccess("https://gitlab.example.com:8443/gl", "custom"),
            GitlabApiAccess("https://gitlab.example.com", "main"),
        ]
        assert all(row[0].merge_status is MergeStatus.MERGED for row in rows)


class TestFindMergedParentsWithChildren:
    """Раздел 16.2: проход ребейза берёт только слитые ветки, на которые ещё опираются дети."""

    async def test_only_pending_parents(self, db_session: AsyncSession) -> None:
        user = await make_user(db_session)
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
