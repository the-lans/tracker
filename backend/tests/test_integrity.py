import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.enums import (
    ManualRequestType,
    NodeLogStatus,
    NodeLogTriggerType,
    NodeType,
    RepositoryRole,
    TaskStatus,
    UserRole,
)
from db.models.logs import NodeLog
from db.models.pipelines import Node, Pipeline, TaskNode
from db.models.prompts import TaskLibraryPrompt, TaskManualRequestQueue
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


async def _make_node(
    session: AsyncSession,
    *,
    created_by: uuid.UUID,
    in_pipeline: bool,
) -> Node:
    pipeline_id = None
    if in_pipeline:
        pipeline = Pipeline(name="п", is_archived=False, created_by=created_by)
        session.add(pipeline)
        await session.flush()
        pipeline_id = pipeline.id
    node = Node(
        created_by=created_by,
        pipeline_id=pipeline_id,
        order_index=0 if in_pipeline else None,
        name="нода",
        node_type=NodeType.PLAIN_PROMPT,
        is_library_item=not in_pipeline,
        is_archived=False,
    )
    session.add(node)
    await session.flush()
    return node


def _reference(kind: str, *, task: Task, node: Node, user_id: uuid.UUID) -> object:
    if kind == "library_prompt":
        return TaskLibraryPrompt(task_id=task.id, node_id=node.id, added_by=user_id)
    if kind == "task_node":
        return TaskNode(task_id=task.id, node_id=node.id, order_index=0)
    if kind == "node_log":
        return NodeLog(
            task_id=task.id,
            node_id=node.id,
            trigger_type=NodeLogTriggerType.PIPELINE,
            attempt_number=1,
            status=NodeLogStatus.SUCCESS,
        )
    return TaskManualRequestQueue(
        task_id=task.id,
        request_type=ManualRequestType.LIBRARY_PROMPT,
        node_id=node.id,
        requested_by=user_id,
    )


class TestEnsureNodeDeletable:
    """Раздел 3.2: ноду, которую использует задача, удалить нельзя."""

    @pytest.mark.parametrize("in_pipeline", [False, True], ids=["library", "pipeline"])
    async def test_unused(self, db_session: AsyncSession, in_pipeline: bool) -> None:
        user = await _make_user(db_session)
        node = await _make_node(db_session, created_by=user.id, in_pipeline=in_pipeline)

        await ensure_node_deletable(db_session, node)

    @pytest.mark.parametrize(
        ("kind", "in_pipeline", "hint"),
        [
            ("library_prompt", False, "архивация"),
            ("queue", False, "архивация"),
            ("node_log", False, "архивация"),
            ("task_node", True, "Пропуск по умолчанию"),
            ("node_log", True, "Пропуск по умолчанию"),
        ],
        ids=[
            "library_attached",
            "library_queued",
            "library_ran",
            "pipeline_snapshot",
            "pipeline_ran",
        ],
    )
    async def test_used(
        self,
        db_session: AsyncSession,
        kind: str,
        in_pipeline: bool,
        hint: str,
    ) -> None:
        user = await _make_user(db_session)
        node = await _make_node(db_session, created_by=user.id, in_pipeline=in_pipeline)
        task = await _make_task(db_session, created_by=user.id, status=TaskStatus.NEW)
        db_session.add(_reference(kind, task=task, node=node, user_id=user.id))
        await db_session.flush()

        with pytest.raises(ConflictError, match=hint):
            await ensure_node_deletable(db_session, node)


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
