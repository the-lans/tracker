"""Тесты `services/gitlab_sync.py` (этап 10 плана реализации).

`GitlabClient` подставляется через `httpx.MockTransport` (см.
`tests/test_gitlab_client.py`) — реального GitLab-инстанса не требуется.
Ребейз дочерних веток упражняется на локальных bare-репозиториях, тем же
способом, что и `tests/test_git_ops.py`.
"""

from __future__ import annotations

import subprocess
import uuid
from pathlib import Path

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
from services.git_ops import clone_task_repository
from services.gitlab_sync import (
    ACCESS_DENIED_KEY,
    permanent_failure_key,
    rebase_child_task_repositories_on_parent_merge,
    sync_merge_statuses,
    sync_task_repository_merge_status,
)
from services.notifications import NotificationEvent

_GIT_AUTHOR_ARGS = ["-c", "user.email=test@example.com", "-c", "user.name=Test"]


def _make_repository(*, git_url: str = "git@gitlab.example.com:g/p.git") -> Repository:
    return Repository(name="r", git_url=git_url, deploy_key_encrypted=encrypt("k"))


def _run(*args: str, cwd: Path) -> str:
    result = subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True)
    return result.stdout


def _init_bare_origin(tmp_path: Path) -> Path:
    origin = tmp_path / "origin.git"
    _run("git", "init", "--bare", "--initial-branch=main", str(origin), cwd=tmp_path)
    seed_dir = tmp_path / "seed"
    _run("git", "clone", str(origin), str(seed_dir), cwd=tmp_path)
    (seed_dir / "README.md").write_text("init\n")
    _run("git", "add", "README.md", cwd=seed_dir)
    _run("git", *_GIT_AUTHOR_ARGS, "commit", "-m", "init", cwd=seed_dir)
    _run("git", "branch", "-M", "main", cwd=seed_dir)
    _run("git", "push", "origin", "main", cwd=seed_dir)
    return origin


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


async def test_rebase_child_task_repositories_skips_when_parent_not_merged(
    db_session: AsyncSession,
) -> None:
    user = await _make_user(db_session)
    task = await _make_task(db_session, created_by=user.id)
    repository = _make_repository()
    db_session.add(repository)
    await db_session.flush()
    parent_task_repository = TaskRepository(
        task_id=task.id,
        repository_id=repository.id,
        role=RepositoryRole.READ_WRITE,
        branch_name="feature/RR-00001",
        base_branch="main",
        merge_status=MergeStatus.PUSHED,
    )
    db_session.add(parent_task_repository)
    await db_session.flush()

    rebased = await rebase_child_task_repositories_on_parent_merge(
        db_session,
        parent_task_repository=parent_task_repository,
        repos_root=Path("/tmp/unused"),
    )

    assert rebased == []


async def test_rebase_child_task_repositories_rebases_matching_children(
    db_session: AsyncSession,
    tmp_path: Path,
) -> None:
    origin = _init_bare_origin(tmp_path)

    # Ветка родителя уже существует в origin (была запушена ранее задачей-родителем).
    parent_pusher_dir = tmp_path / "parent-pusher"
    _run("git", "clone", str(origin), str(parent_pusher_dir), cwd=tmp_path)
    _run("git", "checkout", "-b", "feature/RR-parent", cwd=parent_pusher_dir)
    (parent_pusher_dir / "from_parent.txt").write_text("родительские изменения\n")
    _run("git", "add", "from_parent.txt", cwd=parent_pusher_dir)
    _run("git", *_GIT_AUTHOR_ARGS, "commit", "-m", "работа родителя", cwd=parent_pusher_dir)
    _run("git", "push", "origin", "feature/RR-parent", cwd=parent_pusher_dir)

    user = await _make_user(db_session)
    repository = _make_repository(git_url=str(origin))
    db_session.add(repository)
    await db_session.flush()

    parent_task = await _make_task(db_session, created_by=user.id)
    parent_task_repository = TaskRepository(
        task_id=parent_task.id,
        repository_id=repository.id,
        role=RepositoryRole.READ_WRITE,
        branch_name="feature/RR-parent",
        base_branch="main",
        merge_status=MergeStatus.MERGED,
    )
    db_session.add(parent_task_repository)
    await db_session.flush()

    child_task = await _make_task(db_session, created_by=user.id, parent_task_id=parent_task.id)
    child_task_repository = TaskRepository(
        task_id=child_task.id,
        repository_id=repository.id,
        role=RepositoryRole.READ_WRITE,
        branch_name="feature/RR-child",
        base_branch="feature/RR-parent",
        merge_status=MergeStatus.NOT_PUSHED,
    )
    db_session.add(child_task_repository)
    await db_session.flush()

    # Дочерняя задача клонируется от ветки родителя и добавляет свою работу.
    repos_root = tmp_path / "repos"
    child_repo_dir = await clone_task_repository(
        repository=repository,
        task_repository=child_task_repository,
        task_code=child_task.code,
        repos_root=repos_root,
    )
    (child_repo_dir / "from_child.txt").write_text("работа ребёнка\n")
    _run("git", "add", "from_child.txt", cwd=child_repo_dir)
    _run("git", *_GIT_AUTHOR_ARGS, "commit", "-m", "работа ребёнка", cwd=child_repo_dir)

    # "Смердж родительской ветки в main" — main обновляется содержимым родителя.
    _run("git", "checkout", "main", cwd=parent_pusher_dir)
    _run(
        "git",
        *_GIT_AUTHOR_ARGS,
        "merge",
        "--no-ff",
        "feature/RR-parent",
        "-m",
        "merge parent",
        cwd=parent_pusher_dir,
    )
    _run("git", "push", "origin", "main", cwd=parent_pusher_dir)

    rebased = await rebase_child_task_repositories_on_parent_merge(
        db_session,
        parent_task_repository=parent_task_repository,
        repos_root=repos_root,
    )

    assert rebased == [child_task.id]
    assert child_task_repository.base_branch == "main"
    assert (child_repo_dir / "from_parent.txt").exists()
    assert (child_repo_dir / "from_child.txt").exists()


@pytest.mark.parametrize(
    ("child_status", "expected_status"),
    [
        (TaskStatus.IN_PROGRESS, TaskStatus.REBASE_CONFLICT),
        (TaskStatus.PAUSED, TaskStatus.REBASE_CONFLICT),
        # Из ожидания решения — только признак: воркер разберёт его после решения.
        (TaskStatus.PLAN_REVIEW, TaskStatus.PLAN_REVIEW),
        (TaskStatus.AWAITING_INPUT, TaskStatus.AWAITING_INPUT),
    ],
)
async def test_rebase_child_task_repositories_marks_conflict_on_rebase_conflict(
    db_session: AsyncSession,
    tmp_path: Path,
    child_status: TaskStatus,
    expected_status: TaskStatus,
) -> None:
    origin = _init_bare_origin(tmp_path)

    parent_pusher_dir = tmp_path / "parent-pusher"
    _run("git", "clone", str(origin), str(parent_pusher_dir), cwd=tmp_path)
    _run("git", "checkout", "-b", "feature/RR-parent", cwd=parent_pusher_dir)
    (parent_pusher_dir / "README.md").write_text("родительская версия\n")
    _run("git", "add", "README.md", cwd=parent_pusher_dir)
    _run("git", *_GIT_AUTHOR_ARGS, "commit", "-m", "родитель меняет README", cwd=parent_pusher_dir)
    _run("git", "push", "origin", "feature/RR-parent", cwd=parent_pusher_dir)

    user = await _make_user(db_session)
    repository = _make_repository(git_url=str(origin))
    db_session.add(repository)
    await db_session.flush()

    parent_task = await _make_task(db_session, created_by=user.id)
    parent_task_repository = TaskRepository(
        task_id=parent_task.id,
        repository_id=repository.id,
        role=RepositoryRole.READ_WRITE,
        branch_name="feature/RR-parent",
        base_branch="main",
        merge_status=MergeStatus.MERGED,
    )
    db_session.add(parent_task_repository)
    await db_session.flush()

    child_task = await _make_task(
        db_session,
        created_by=user.id,
        parent_task_id=parent_task.id,
        status=child_status,
    )
    child_task_repository = TaskRepository(
        task_id=child_task.id,
        repository_id=repository.id,
        role=RepositoryRole.READ_WRITE,
        branch_name="feature/RR-child",
        base_branch="feature/RR-parent",
        merge_status=MergeStatus.NOT_PUSHED,
    )
    db_session.add(child_task_repository)
    await db_session.flush()

    repos_root = tmp_path / "repos"
    child_repo_dir = await clone_task_repository(
        repository=repository,
        task_repository=child_task_repository,
        task_code=child_task.code,
        repos_root=repos_root,
    )
    # Дочерняя задача КОНФЛИКТУЮЩЕ меняет тот же файл.
    (child_repo_dir / "README.md").write_text("версия ребёнка\n")
    _run("git", "add", "README.md", cwd=child_repo_dir)
    _run(
        "git",
        *_GIT_AUTHOR_ARGS,
        "commit",
        "-m",
        "ребёнок меняет README иначе",
        cwd=child_repo_dir,
    )

    # Родитель мерджится в main.
    _run("git", "checkout", "main", cwd=parent_pusher_dir)
    _run(
        "git",
        *_GIT_AUTHOR_ARGS,
        "merge",
        "--no-ff",
        "feature/RR-parent",
        "-m",
        "merge parent",
        cwd=parent_pusher_dir,
    )
    # После мерджа main ЕЩЁ РАЗ меняет тот же файл иначе — именно это
    # расхождение с ожиданиями коммита ребёнка гарантирует конфликт
    # ребейза (без этого патч ребёнка применился бы поверх main чисто,
    # поскольку main до этого момента совпадает с тем, от чего ребёнок
    # изначально ответвился).
    (parent_pusher_dir / "README.md").write_text("независимая правка main после мерджа\n")
    _run("git", "add", "README.md", cwd=parent_pusher_dir)
    _run(
        "git",
        *_GIT_AUTHOR_ARGS,
        "commit",
        "-m",
        "main меняет README ещё раз",
        cwd=parent_pusher_dir,
    )
    _run("git", "push", "origin", "main", cwd=parent_pusher_dir)

    rebased = await rebase_child_task_repositories_on_parent_merge(
        db_session,
        parent_task_repository=parent_task_repository,
        repos_root=repos_root,
    )

    assert rebased == []
    await db_session.refresh(child_task)
    await db_session.refresh(child_task_repository)
    assert child_task.status is expected_status
    # Признак переживает уход задачи в `failed` (services/rebase_resolution.py).
    assert child_task_repository.merge_status is MergeStatus.CONFLICT


@pytest.mark.parametrize(
    "child_status",
    [TaskStatus.NEW, TaskStatus.QUEUED, TaskStatus.DONE, TaskStatus.FAILED],
)
async def test_rebase_skips_children_without_live_session(
    db_session: AsyncSession,
    tmp_path: Path,
    child_status: TaskStatus,
) -> None:
    """Решение 2026-10-19: done/failed не ребейзятся; new/queued склонируют
    свежую базу при старте. Базовая ветка переключается всё равно."""
    user = await _make_user(db_session)
    repository = _make_repository(git_url=str(tmp_path / "нет-такого-origin.git"))
    db_session.add(repository)
    await db_session.flush()
    parent_task = await _make_task(db_session, created_by=user.id)
    parent_task_repository = TaskRepository(
        task_id=parent_task.id,
        repository_id=repository.id,
        role=RepositoryRole.READ_WRITE,
        branch_name="feature/RR-parent",
        base_branch="main",
        merge_status=MergeStatus.MERGED,
    )
    child_task = await _make_task(
        db_session,
        created_by=user.id,
        parent_task_id=parent_task.id,
        status=child_status,
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

    rebased = await rebase_child_task_repositories_on_parent_merge(
        db_session,
        parent_task_repository=parent_task_repository,
        repos_root=tmp_path / "repos",
    )

    assert rebased == []
    assert child_task_repository.base_branch == "main"
    await db_session.refresh(child_task)
    assert child_task.status is child_status


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
