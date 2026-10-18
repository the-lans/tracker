import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.enums import NodeLogStatus, NodeLogTriggerType, TaskStatus, UserRole
from db.models.logs import NodeLog
from db.models.tasks import Task
from db.models.users import User
from services.errors import ConflictError
from services.nodes.clear_context import ensure_clear_context_allowed


async def _make_task(db_session: AsyncSession) -> Task:
    user = User(email=f"{uuid.uuid4()}@example.com", role=UserRole.USER)
    db_session.add(user)
    await db_session.flush()
    task = Task(
        code=f"RR-{uuid.uuid4().hex[:5]}",
        title="t",
        description="d",
        created_by=user.id,
        status=TaskStatus.IN_PROGRESS,
    )
    db_session.add(task)
    await db_session.flush()
    return task


async def test_clear_context_allowed_when_no_blocking_node_logs(db_session: AsyncSession) -> None:
    task = await _make_task(db_session)
    db_session.add(
        NodeLog(
            task_id=task.id,
            trigger_type=NodeLogTriggerType.PIPELINE,
            status=NodeLogStatus.SUCCESS,
        ),
    )
    await db_session.flush()

    await ensure_clear_context_allowed(db_session, task.id)


@pytest.mark.parametrize("status", [NodeLogStatus.RUNNING, NodeLogStatus.AWAITING_DECISION])
async def test_clear_context_rejected_with_blocking_node_logs(
    db_session: AsyncSession,
    status: NodeLogStatus,
) -> None:
    task = await _make_task(db_session)
    db_session.add(
        NodeLog(task_id=task.id, trigger_type=NodeLogTriggerType.PIPELINE, status=status),
    )
    await db_session.flush()

    with pytest.raises(ConflictError):
        await ensure_clear_context_allowed(db_session, task.id)


async def test_clear_context_allowed_for_task_with_no_node_logs(db_session: AsyncSession) -> None:
    task = await _make_task(db_session)

    await ensure_clear_context_allowed(db_session, task.id)
