import uuid
from datetime import UTC, datetime

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.enums import (
    LibraryPromptRunStatus,
    ManualRequestStatus,
    ManualRequestType,
    NodeLogStatus,
    NodeLogTriggerType,
    NodeType,
    TaskStatus,
    UserRole,
)
from db.models.logs import AppLog, NodeLog
from db.models.pipelines import Node, Pipeline, TaskNode
from db.models.prompts import TaskLibraryPrompt, TaskManualRequestQueue
from db.models.tasks import Task
from db.models.users import User
from services.errors import ConflictError, ValidationError
from services.task_status import (
    fail_task_after_error,
    first_unfinished_order_index,
    transition_task_status,
)


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
        (TaskStatus.QUEUED, TaskStatus.NEW),
        (TaskStatus.IN_PROGRESS, TaskStatus.PAUSED),
        (TaskStatus.PAUSED, TaskStatus.IN_PROGRESS),
        (TaskStatus.PAUSED, TaskStatus.REBASE_CONFLICT),
        (TaskStatus.IN_PROGRESS, TaskStatus.PLAN_REVIEW),
        (TaskStatus.IN_PROGRESS, TaskStatus.AWAITING_INPUT),
        (TaskStatus.IN_PROGRESS, TaskStatus.REBASE_CONFLICT),
        (TaskStatus.PLAN_REVIEW, TaskStatus.IN_PROGRESS),
        (TaskStatus.AWAITING_INPUT, TaskStatus.IN_PROGRESS),
        (TaskStatus.PAUSED, TaskStatus.PLAN_REVIEW),
        (TaskStatus.PAUSED, TaskStatus.AWAITING_INPUT),
        (TaskStatus.PLAN_REVIEW, TaskStatus.PAUSED),
        (TaskStatus.AWAITING_INPUT, TaskStatus.PAUSED),
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
        (TaskStatus.PAUSED, TaskStatus.DONE),
        (TaskStatus.NEW, TaskStatus.PAUSED),
        (TaskStatus.REBASE_CONFLICT, TaskStatus.DONE),
        (TaskStatus.PLAN_REVIEW, TaskStatus.REBASE_CONFLICT),
        (TaskStatus.AWAITING_INPUT, TaskStatus.DONE),
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


async def test_extra_values_are_written_in_the_same_update(db_session: AsyncSession) -> None:
    task = await _make_task(db_session, status=TaskStatus.QUEUED)
    task.auto_start_enabled = True
    await db_session.flush()

    updated = await transition_task_status(
        db_session,
        task_id=task.id,
        from_status=TaskStatus.QUEUED,
        to_status=TaskStatus.NEW,
        extra_values={"auto_start_enabled": False},
    )

    assert updated.status is TaskStatus.NEW
    assert updated.auto_start_enabled is False


@pytest.mark.parametrize("from_status", [TaskStatus.PAUSED, TaskStatus.REBASE_CONFLICT])
async def test_failed_reachable_from_paused_and_rebase_conflict(
    db_session: AsyncSession,
    from_status: TaskStatus,
) -> None:
    task = await _make_task(db_session, status=from_status)

    updated = await transition_task_status(
        db_session,
        task_id=task.id,
        from_status=from_status,
        to_status=TaskStatus.FAILED,
        failed_order_index=1,
    )

    assert updated.status is TaskStatus.FAILED
    assert updated.last_failed_order_index == 1


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


async def _log_success(db_session: AsyncSession, task: Task, node: Node) -> None:
    db_session.add(
        NodeLog(
            task_id=task.id,
            node_id=node.id,
            trigger_type=NodeLogTriggerType.PIPELINE,
            status=NodeLogStatus.SUCCESS,
        ),
    )
    await db_session.flush()


async def test_first_unfinished_order_index_points_to_first_node_without_success(
    db_session: AsyncSession,
) -> None:
    task = await _make_task(db_session, status=TaskStatus.IN_PROGRESS)
    first = await _add_enabled_node(db_session, task, order_index=0)
    await _add_enabled_node(db_session, task, order_index=1)
    await _log_success(db_session, task, first)

    assert await first_unfinished_order_index(db_session, task.id) == 1


async def test_first_unfinished_order_index_is_past_last_node_when_all_succeeded(
    db_session: AsyncSession,
) -> None:
    task = await _make_task(db_session, status=TaskStatus.IN_PROGRESS)
    for order_index in (0, 3):
        node = await _add_enabled_node(db_session, task, order_index=order_index)
        await _log_success(db_session, task, node)

    # Сбой после всех нод (например, при пуше): перезапуск нод не повторяет.
    assert await first_unfinished_order_index(db_session, task.id) == 4


@pytest.mark.parametrize(
    "status",
    [
        TaskStatus.IN_PROGRESS,
        TaskStatus.AWAITING_INPUT,
        TaskStatus.PAUSED,
        TaskStatus.REBASE_CONFLICT,
    ],
)
async def test_fail_task_after_error_fails_task_and_closes_running_logs(
    db_session: AsyncSession,
    status: TaskStatus,
) -> None:
    task = await _make_task(db_session, status=status)
    node = await _add_enabled_node(db_session, task, order_index=2)
    running_log = NodeLog(
        task_id=task.id,
        node_id=node.id,
        trigger_type=NodeLogTriggerType.PIPELINE,
        status=NodeLogStatus.RUNNING,
    )
    db_session.add(running_log)
    await db_session.commit()

    await fail_task_after_error(db_session, task_id=task.id, error=RuntimeError("SDK упал"))

    await db_session.refresh(task)
    await db_session.refresh(running_log)
    assert task.status is TaskStatus.FAILED
    assert task.last_failed_order_index == 2
    assert running_log.status is NodeLogStatus.FAILED
    app_logs = (
        await db_session.execute(sa.select(AppLog).where(AppLog.task_id == task.id))
    ).scalars().all()
    assert ["SDK упал" in log.message for log in app_logs] == [True]


async def test_fail_task_after_error_leaves_terminal_task_untouched(
    db_session: AsyncSession,
) -> None:
    task = await _make_task(db_session, status=TaskStatus.DONE)
    await db_session.commit()

    await fail_task_after_error(db_session, task_id=task.id, error=RuntimeError("поздно"))

    await db_session.refresh(task)
    assert task.status is TaskStatus.DONE


class TestFailTaskClosesManualRun:
    async def test_closes_request_and_prompt(
        self,
        db_session: AsyncSession,
    ) -> None:
        """
        Иначе `processing`-запрос и «выполняется» у промта библиотеки висели
        бы вечно: очередь берёт только `queued`.
        """
        task = await _make_task(db_session, status=TaskStatus.IN_PROGRESS)
        node = await _add_enabled_node(db_session, task, order_index=0)
        request = TaskManualRequestQueue(
            task_id=task.id,
            request_type=ManualRequestType.LIBRARY_PROMPT,
            node_id=node.id,
            requested_by=task.created_by,
            status=ManualRequestStatus.PROCESSING,
            requested_at=datetime.now(UTC),
        )
        library_prompt = TaskLibraryPrompt(
            task_id=task.id,
            node_id=node.id,
            added_by=task.created_by,
            last_run_status=LibraryPromptRunStatus.RUNNING,
        )
        db_session.add_all([request, library_prompt])
        await db_session.commit()

        await fail_task_after_error(db_session, task_id=task.id, error=RuntimeError("SDK упал"))

        await db_session.refresh(request)
        await db_session.refresh(library_prompt)
        assert request.status is ManualRequestStatus.DONE
        assert request.processed_at is not None
        assert library_prompt.last_run_status is LibraryPromptRunStatus.FAILED
        assert library_prompt.last_run_at is not None
