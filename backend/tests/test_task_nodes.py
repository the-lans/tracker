"""Тесты `services/task_nodes.py` — правила редактирования `task_nodes.is_enabled`
(раздел 13.2 ТЗ, правило 11 CLAUDE.md)."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest

from db.models.enums import NodeType, TaskStatus, UserRole
from db.models.pipelines import Node, Pipeline, TaskNode
from db.models.tasks import Task
from db.models.users import User
from services.errors import ConflictError, NotFoundError
from services.task_nodes import list_task_nodes, set_task_node_enabled

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def _make_task_with_nodes(
    db_session: AsyncSession,
    *,
    status: TaskStatus,
    last_failed_order_index: int | None = None,
    node_count: int = 3,
) -> tuple[Task, list[TaskNode]]:
    user = User(email=f"{uuid.uuid4()}@example.com", role=UserRole.USER)
    pipeline = Pipeline(name="p", is_archived=False)
    db_session.add_all([user, pipeline])
    await db_session.flush()
    task = Task(
        code=f"RR-{uuid.uuid4().hex[:5]}",
        title="t",
        description="d",
        created_by=user.id,
        pipeline_id=pipeline.id,
        status=status,
        last_failed_order_index=last_failed_order_index,
    )
    db_session.add(task)
    await db_session.flush()
    task_nodes = []
    for order_index in range(node_count):
        node = Node(
            pipeline_id=pipeline.id,
            order_index=order_index,
            name=f"node-{order_index}",
            node_type=NodeType.PLAIN_PROMPT,
            prompt_template="x",
            timeout_seconds=60,
            max_retries=1,
            retry_base_delay_seconds=0,
            is_skipped=False,
            is_library_item=False,
            is_archived=False,
        )
        db_session.add(node)
        await db_session.flush()
        task_node = TaskNode(task_id=task.id, node_id=node.id, order_index=order_index)
        db_session.add(task_node)
        task_nodes.append(task_node)
    await db_session.flush()
    return task, task_nodes


async def test_new_task_allows_toggling_any_node(db_session: AsyncSession) -> None:
    task, task_nodes = await _make_task_with_nodes(db_session, status=TaskStatus.NEW)

    for task_node in task_nodes:
        await set_task_node_enabled(
            db_session,
            task=task,
            task_node_id=task_node.id,
            is_enabled=False,
        )

    views = await list_task_nodes(db_session, task)
    assert [view.is_enabled for view in views] == [False, False, False]
    assert [view.editable for view in views] == [True, True, True]
    assert [view.name for view in views] == ["node-0", "node-1", "node-2"]


async def test_failed_task_allows_only_nodes_after_failure_point(
    db_session: AsyncSession,
) -> None:
    task, task_nodes = await _make_task_with_nodes(
        db_session,
        status=TaskStatus.FAILED,
        last_failed_order_index=1,
    )

    await set_task_node_enabled(
        db_session,
        task=task,
        task_node_id=task_nodes[2].id,
        is_enabled=False,
    )
    for locked in task_nodes[:2]:
        with pytest.raises(ConflictError, match="уже выполнялась"):
            await set_task_node_enabled(
                db_session,
                task=task,
                task_node_id=locked.id,
                is_enabled=False,
            )

    views = await list_task_nodes(db_session, task)
    assert [view.editable for view in views] == [False, False, True]
    assert [view.is_enabled for view in views] == [True, True, False]


@pytest.mark.parametrize(
    "status",
    [TaskStatus.QUEUED, TaskStatus.IN_PROGRESS, TaskStatus.PAUSED, TaskStatus.DONE],
)
async def test_started_task_locks_all_nodes(
    db_session: AsyncSession,
    status: TaskStatus,
) -> None:
    task, task_nodes = await _make_task_with_nodes(db_session, status=status, node_count=1)

    with pytest.raises(ConflictError, match="только до запуска"):
        await set_task_node_enabled(
            db_session,
            task=task,
            task_node_id=task_nodes[0].id,
            is_enabled=False,
        )


async def test_node_of_another_task_is_not_found(db_session: AsyncSession) -> None:
    task, _ = await _make_task_with_nodes(db_session, status=TaskStatus.NEW, node_count=1)
    _other_task, other_nodes = await _make_task_with_nodes(
        db_session,
        status=TaskStatus.NEW,
        node_count=1,
    )

    with pytest.raises(NotFoundError):
        await set_task_node_enabled(
            db_session,
            task=task,
            task_node_id=other_nodes[0].id,
            is_enabled=False,
        )
