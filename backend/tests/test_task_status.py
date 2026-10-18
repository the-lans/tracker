import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.enums import NodeLogStatus, NodeLogTriggerType, NodeType, TaskStatus, UserRole
from db.models.logs import NodeLog
from db.models.pipelines import Node, Pipeline, TaskNode
from db.models.tasks import Task
from db.models.users import User
from services.errors import ConflictError, ValidationError
from services.task_status import transition_task_status


async def _make_task(db_session: AsyncSession, *, status: TaskStatus = TaskStatus.NEW) -> Task:
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
    return task


async def _add_enabled_node(db_session: AsyncSession, task: Task, *, order_index: int) -> Node:
    pipeline = await db_session.get(Pipeline, task.pipeline_id) if task.pipeline_id else None
    if pipeline is None:
        pipeline = Pipeline(name="p", is_archived=False)
        db_session.add(pipeline)
        await db_session.flush()
        task.pipeline_id = pipeline.id
        await db_session.flush()
    node = Node(
        pipeline_id=pipeline.id,
        order_index=order_index,
        name=f"n{order_index}",
        node_type=NodeType.PLAIN_PROMPT,
        prompt_template="x",
        timeout_seconds=60,
        max_retries=3,
        retry_base_delay_seconds=1,
        is_skipped=False,
        is_library_item=False,
        is_archived=False,
    )
    db_session.add(node)
    await db_session.flush()
    db_session.add(
        TaskNode(task_id=task.id, node_id=node.id, order_index=order_index, is_enabled=True),
    )
    await db_session.flush()
    return node


@pytest.mark.parametrize(
    ("from_status", "to_status"),
    [
        (TaskStatus.NEW, TaskStatus.QUEUED),
        (TaskStatus.QUEUED, TaskStatus.IN_PROGRESS),
        (TaskStatus.IN_PROGRESS, TaskStatus.PLAN_REVIEW),
        (TaskStatus.IN_PROGRESS, TaskStatus.AWAITING_INPUT),
        (TaskStatus.IN_PROGRESS, TaskStatus.REBASE_CONFLICT),
        (TaskStatus.PLAN_REVIEW, TaskStatus.IN_PROGRESS),
        (TaskStatus.AWAITING_INPUT, TaskStatus.IN_PROGRESS),
        (TaskStatus.REBASE_CONFLICT, TaskStatus.IN_PROGRESS),
        (TaskStatus.FAILED, TaskStatus.IN_PROGRESS),
    ],
)
async def test_allowed_transitions_succeed(
    db_session: AsyncSession,
    from_status: TaskStatus,
    to_status: TaskStatus,
) -> None:
    task = await _make_task(db_session, status=from_status)

    updated = await transition_task_status(
        db_session,
        task_id=task.id,
        from_status=from_status,
        to_status=to_status,
    )

    assert updated.status is to_status


@pytest.mark.parametrize(
    ("from_status", "to_status"),
    [
        (TaskStatus.NEW, TaskStatus.IN_PROGRESS),
        (TaskStatus.DONE, TaskStatus.IN_PROGRESS),
        (TaskStatus.IN_PROGRESS, TaskStatus.NEW),
        (TaskStatus.QUEUED, TaskStatus.DONE),
    ],
)
async def test_disallowed_transitions_are_rejected(
    db_session: AsyncSession,
    from_status: TaskStatus,
    to_status: TaskStatus,
) -> None:
    task = await _make_task(db_session, status=from_status)

    with pytest.raises(ValidationError):
        await transition_task_status(
            db_session,
            task_id=task.id,
            from_status=from_status,
            to_status=to_status,
        )


async def test_compare_and_swap_rejects_stale_from_status(db_session: AsyncSession) -> None:
    task = await _make_task(db_session, status=TaskStatus.NEW)
    # Кто-то другой уже перевёл задачу в queued до нас.
    await transition_task_status(
        db_session,
        task_id=task.id,
        from_status=TaskStatus.NEW,
        to_status=TaskStatus.QUEUED,
    )

    with pytest.raises(ConflictError):
        await transition_task_status(
            db_session,
            task_id=task.id,
            from_status=TaskStatus.NEW,
            to_status=TaskStatus.QUEUED,
        )


async def test_failed_transition_requires_order_index(db_session: AsyncSession) -> None:
    task = await _make_task(db_session, status=TaskStatus.IN_PROGRESS)

    with pytest.raises(ValidationError):
        await transition_task_status(
            db_session,
            task_id=task.id,
            from_status=TaskStatus.IN_PROGRESS,
            to_status=TaskStatus.FAILED,
        )


async def test_failed_transition_records_order_index(db_session: AsyncSession) -> None:
    task = await _make_task(db_session, status=TaskStatus.IN_PROGRESS)

    updated = await transition_task_status(
        db_session,
        task_id=task.id,
        from_status=TaskStatus.IN_PROGRESS,
        to_status=TaskStatus.FAILED,
        failed_order_index=2,
    )

    assert updated.last_failed_order_index == 2


async def test_done_transition_blocked_until_all_enabled_nodes_succeed(
    db_session: AsyncSession,
) -> None:
    task = await _make_task(db_session, status=TaskStatus.IN_PROGRESS)
    node_a = await _add_enabled_node(db_session, task, order_index=0)
    await _add_enabled_node(db_session, task, order_index=1)
    db_session.add(
        NodeLog(
            task_id=task.id,
            node_id=node_a.id,
            trigger_type=NodeLogTriggerType.PIPELINE,
            status=NodeLogStatus.SUCCESS,
        ),
    )
    await db_session.flush()

    with pytest.raises(ValidationError):
        await transition_task_status(
            db_session,
            task_id=task.id,
            from_status=TaskStatus.IN_PROGRESS,
            to_status=TaskStatus.DONE,
        )


async def test_done_transition_succeeds_when_all_enabled_nodes_succeeded(
    db_session: AsyncSession,
) -> None:
    task = await _make_task(db_session, status=TaskStatus.IN_PROGRESS)
    node_a = await _add_enabled_node(db_session, task, order_index=0)
    node_b = await _add_enabled_node(db_session, task, order_index=1)
    for node in (node_a, node_b):
        db_session.add(
            NodeLog(
                task_id=task.id,
                node_id=node.id,
                trigger_type=NodeLogTriggerType.PIPELINE,
                status=NodeLogStatus.SUCCESS,
            ),
        )
    await db_session.flush()

    updated = await transition_task_status(
        db_session,
        task_id=task.id,
        from_status=TaskStatus.IN_PROGRESS,
        to_status=TaskStatus.DONE,
    )

    assert updated.status is TaskStatus.DONE


async def test_done_transition_succeeds_trivially_with_no_enabled_nodes(
    db_session: AsyncSession,
) -> None:
    task = await _make_task(db_session, status=TaskStatus.IN_PROGRESS)

    updated = await transition_task_status(
        db_session,
        task_id=task.id,
        from_status=TaskStatus.IN_PROGRESS,
        to_status=TaskStatus.DONE,
    )

    assert updated.status is TaskStatus.DONE
