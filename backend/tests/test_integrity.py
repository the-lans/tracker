import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.enums import NodeType, RepositoryRole, TaskStatus, UserRole
from db.models.pipelines import Node, Pipeline
from db.models.prompts import TaskLibraryPrompt
from db.models.repositories import Repository
from db.models.tasks import Task, TaskRepository
from db.models.users import User
from services.errors import ConflictError
from services.integrity import (
    ensure_node_deletable,
    ensure_pipeline_deletable,
    ensure_repository_deletable,
)


async def _make_user(session: AsyncSession) -> User:
    user = User(email=f"{uuid.uuid4()}@example.com", role=UserRole.ADMIN)
    session.add(user)
    await session.flush()
    return user


async def _make_task(session: AsyncSession, *, created_by: uuid.UUID, status: TaskStatus) -> Task:
    task = Task(
        code=f"RR-{uuid.uuid4().hex[:5]}",
        title="задача",
        description="описание",
        created_by=created_by,
        status=status,
    )
    session.add(task)
    await session.flush()
    return task


async def test_ensure_pipeline_deletable_allows_unused_pipeline(db_session: AsyncSession) -> None:
    user = await _make_user(db_session)
    pipeline = Pipeline(name="пайплайн", created_by=user.id)
    db_session.add(pipeline)
    await db_session.flush()

    await ensure_pipeline_deletable(db_session, pipeline.id)


async def test_ensure_pipeline_deletable_rejects_pipeline_used_by_task(
    db_session: AsyncSession,
) -> None:
    user = await _make_user(db_session)
    pipeline = Pipeline(name="пайплайн", created_by=user.id)
    db_session.add(pipeline)
    await db_session.flush()
    task = await _make_task(db_session, created_by=user.id, status=TaskStatus.NEW)
    task.pipeline_id = pipeline.id
    await db_session.flush()

    with pytest.raises(ConflictError):
        await ensure_pipeline_deletable(db_session, pipeline.id)


async def test_ensure_node_deletable_allows_unused_library_prompt(db_session: AsyncSession) -> None:
    user = await _make_user(db_session)
    node = Node(
        created_by=user.id,
        name="промт",
        node_type=NodeType.PLAIN_PROMPT,
        is_library_item=True,
        is_archived=False,
    )
    db_session.add(node)
    await db_session.flush()

    await ensure_node_deletable(db_session, node.id)


async def test_ensure_node_deletable_rejects_node_used_by_task(db_session: AsyncSession) -> None:
    user = await _make_user(db_session)
    node = Node(
        created_by=user.id,
        name="промт",
        node_type=NodeType.PLAIN_PROMPT,
        is_library_item=True,
        is_archived=False,
    )
    db_session.add(node)
    await db_session.flush()
    task = await _make_task(db_session, created_by=user.id, status=TaskStatus.NEW)
    db_session.add(
        TaskLibraryPrompt(task_id=task.id, node_id=node.id, added_by=user.id),
    )
    await db_session.flush()

    with pytest.raises(ConflictError):
        await ensure_node_deletable(db_session, node.id)


@pytest.mark.parametrize(
    ("task_status", "expected_deletable"),
    [
        (TaskStatus.NEW, False),
        (TaskStatus.IN_PROGRESS, False),
        (TaskStatus.DONE, True),
        (TaskStatus.FAILED, True),
    ],
)
async def test_ensure_repository_deletable_depends_on_task_terminality(
    db_session: AsyncSession,
    task_status: TaskStatus,
    expected_deletable: bool,
) -> None:
    user = await _make_user(db_session)
    repository = Repository(
        name="repo",
        git_url="git@example.com:x.git",
        deploy_key_encrypted="enc",
    )
    db_session.add(repository)
    await db_session.flush()
    task = await _make_task(db_session, created_by=user.id, status=task_status)
    db_session.add(
        TaskRepository(
            task_id=task.id,
            repository_id=repository.id,
            role=RepositoryRole.READ_WRITE,
            branch_name="feature/RR-00001",
            base_branch="main",
        ),
    )
    await db_session.flush()

    if expected_deletable:
        await ensure_repository_deletable(db_session, repository.id)
    else:
        with pytest.raises(ConflictError):
            await ensure_repository_deletable(db_session, repository.id)
