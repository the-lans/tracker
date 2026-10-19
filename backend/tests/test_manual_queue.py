import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import sqlalchemy as sa
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from clients.claude_agent import ClaudeCodeSession
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
from db.models.logs import NodeLog
from db.models.pipelines import Node
from db.models.prompts import TaskLibraryPrompt, TaskManualRequestQueue
from db.models.tasks import Task
from db.models.users import User
from services.distributed_lock import acquire_task_operation_lock
from services.errors import ConflictError, ValidationError
from services.manual_queue import (
    LIBRARY_FORBIDDEN_NODE_TYPES,
    MANUAL_QUEUE_LOCK_OPERATION,
    cancel_manual_request,
    enqueue_freeform_prompt_run,
    enqueue_library_prompt_run,
    expire_stale_manual_queue_requests,
    process_manual_queue_once,
)
from services.task_control import (
    TaskControlCommand,
    is_manual_stop_requested,
    request_manual_stop,
    request_task_control,
)
from tests.fakes import FakeClaudeAgentClient, make_result_message

_GENEROUS_TIMEOUT_SECONDS = 30


async def _make_task(db_session: AsyncSession) -> tuple[Task, uuid.UUID]:
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
    return task, user.id


async def _make_library_node(
    db_session: AsyncSession,
    *,
    node_type: NodeType = NodeType.PLAIN_PROMPT,
    prompt_template: str | None = "библиотечный промт",
) -> Node:
    node = Node(
        name="library-node",
        node_type=node_type,
        prompt_template=prompt_template if node_type is NodeType.PLAIN_PROMPT else None,
        command_invocation="/do-thing" if node_type is NodeType.SLASH_COMMAND else None,
        timeout_seconds=_GENEROUS_TIMEOUT_SECONDS,
        max_retries=3,
        retry_base_delay_seconds=0,
        is_skipped=False,
        is_library_item=True,
        is_archived=False,
    )
    db_session.add(node)
    await db_session.flush()
    return node


async def _node_logs_for(db_session: AsyncSession, task_id: uuid.UUID) -> list[NodeLog]:
    stmt = sa.select(NodeLog).where(NodeLog.task_id == task_id).order_by(NodeLog.started_at)
    return list((await db_session.execute(stmt)).scalars().all())


async def test_enqueue_library_prompt_run_creates_queued_request(db_session: AsyncSession) -> None:
    task, user_id = await _make_task(db_session)
    node = await _make_library_node(db_session)
    task_library_prompt = TaskLibraryPrompt(task_id=task.id, node_id=node.id, added_by=user_id)
    db_session.add(task_library_prompt)
    await db_session.flush()

    request = await enqueue_library_prompt_run(
        db_session,
        task_library_prompt=task_library_prompt,
        node=node,
        requested_by=user_id,
    )

    assert request.status is ManualRequestStatus.QUEUED
    assert request.request_type is ManualRequestType.LIBRARY_PROMPT
    assert task_library_prompt.last_run_status is LibraryPromptRunStatus.QUEUED


@pytest.mark.parametrize("node_type", sorted(LIBRARY_FORBIDDEN_NODE_TYPES))
async def test_enqueue_library_prompt_run_rejects_forbidden_node_types(
    db_session: AsyncSession,
    node_type: NodeType,
) -> None:
    task, user_id = await _make_task(db_session)
    node = await _make_library_node(db_session, node_type=node_type, prompt_template=None)
    task_library_prompt = TaskLibraryPrompt(task_id=task.id, node_id=node.id, added_by=user_id)
    db_session.add(task_library_prompt)
    await db_session.flush()

    with pytest.raises(ValidationError):
        await enqueue_library_prompt_run(
            db_session,
            task_library_prompt=task_library_prompt,
            node=node,
            requested_by=user_id,
        )


async def test_enqueue_freeform_prompt_run_creates_queued_request(db_session: AsyncSession) -> None:
    task, user_id = await _make_task(db_session)

    request = await enqueue_freeform_prompt_run(
        db_session,
        task_id=task.id,
        raw_prompt_text="Проверь {{task.code}}",
        requested_by=user_id,
    )

    assert request.status is ManualRequestStatus.QUEUED
    assert request.request_type is ManualRequestType.FREEFORM_PROMPT


async def test_enqueue_freeform_prompt_run_rejects_node_variables(db_session: AsyncSession) -> None:
    task, user_id = await _make_task(db_session)

    with pytest.raises(ValidationError):
        await enqueue_freeform_prompt_run(
            db_session,
            task_id=task.id,
            raw_prompt_text="Используй {{node.script_output}}",
            requested_by=user_id,
        )


async def test_cancel_manual_request_succeeds_when_queued(db_session: AsyncSession) -> None:
    task, user_id = await _make_task(db_session)
    request = await enqueue_freeform_prompt_run(
        db_session,
        task_id=task.id,
        raw_prompt_text="привет",
        requested_by=user_id,
    )

    await cancel_manual_request(db_session, request)

    assert request.status is ManualRequestStatus.CANCELLED


@pytest.mark.parametrize(
    "status",
    [ManualRequestStatus.PROCESSING, ManualRequestStatus.DONE, ManualRequestStatus.CANCELLED],
)
async def test_cancel_manual_request_rejects_when_not_queued(
    db_session: AsyncSession,
    status: ManualRequestStatus,
) -> None:
    task, user_id = await _make_task(db_session)
    request = TaskManualRequestQueue(
        task_id=task.id,
        request_type=ManualRequestType.FREEFORM_PROMPT,
        raw_prompt_text="привет",
        requested_by=user_id,
        status=status,
    )
    db_session.add(request)
    await db_session.flush()

    with pytest.raises(ConflictError):
        await cancel_manual_request(db_session, request)


async def test_process_manual_queue_once_returns_zero_when_empty(
    db_session: AsyncSession,
    tmp_path: Path,
    redis_client: Redis,
) -> None:
    task, _user_id = await _make_task(db_session)
    session = ClaudeCodeSession(FakeClaudeAgentClient(messages_per_query=[]))

    processed = await process_manual_queue_once(
        db_session,
        task=task,
        claude_session=session,
        repos_path=tmp_path,
        redis_client=redis_client,
    )

    assert processed == 0


async def test_process_manual_queue_once_runs_library_prompt_and_updates_status(
    db_session: AsyncSession,
    tmp_path: Path,
    redis_client: Redis,
) -> None:
    task, user_id = await _make_task(db_session)
    node = await _make_library_node(db_session)
    task_library_prompt = TaskLibraryPrompt(task_id=task.id, node_id=node.id, added_by=user_id)
    db_session.add(task_library_prompt)
    await db_session.flush()
    await enqueue_library_prompt_run(
        db_session,
        task_library_prompt=task_library_prompt,
        node=node,
        requested_by=user_id,
    )
    fake = FakeClaudeAgentClient(messages_per_query=[[make_result_message()]])
    session = ClaudeCodeSession(fake)

    processed = await process_manual_queue_once(
        db_session,
        task=task,
        claude_session=session,
        repos_path=tmp_path,
        redis_client=redis_client,
    )

    assert processed == 1
    assert task_library_prompt.last_run_status is LibraryPromptRunStatus.SUCCESS
    logs = await _node_logs_for(db_session, task.id)
    assert len(logs) == 1
    assert logs[0].trigger_type is NodeLogTriggerType.LIBRARY_MANUAL
    assert logs[0].status is NodeLogStatus.SUCCESS


async def test_process_manual_queue_once_marks_library_prompt_failed_on_error(
    db_session: AsyncSession,
    tmp_path: Path,
    redis_client: Redis,
) -> None:
    task, user_id = await _make_task(db_session)
    node = await _make_library_node(db_session)
    task_library_prompt = TaskLibraryPrompt(task_id=task.id, node_id=node.id, added_by=user_id)
    db_session.add(task_library_prompt)
    await db_session.flush()
    await enqueue_library_prompt_run(
        db_session,
        task_library_prompt=task_library_prompt,
        node=node,
        requested_by=user_id,
    )
    fake = FakeClaudeAgentClient(messages_per_query=[[make_result_message(is_error=True)]])
    session = ClaudeCodeSession(fake)

    await process_manual_queue_once(
        db_session,
        task=task,
        claude_session=session,
        repos_path=tmp_path,
        redis_client=redis_client,
    )

    assert task_library_prompt.last_run_status is LibraryPromptRunStatus.FAILED
    # Раздел 7.4/11.7: без retry — ровно одна попытка.
    assert len(fake.queries) == 1


async def test_process_manual_queue_once_runs_freeform_prompt(
    db_session: AsyncSession,
    tmp_path: Path,
    redis_client: Redis,
) -> None:
    task, user_id = await _make_task(db_session)
    await enqueue_freeform_prompt_run(
        db_session,
        task_id=task.id,
        raw_prompt_text="привет из свободного поля",
        requested_by=user_id,
    )
    fake = FakeClaudeAgentClient(messages_per_query=[[make_result_message()]])
    session = ClaudeCodeSession(fake)

    processed = await process_manual_queue_once(
        db_session,
        task=task,
        claude_session=session,
        repos_path=tmp_path,
        redis_client=redis_client,
    )

    assert processed == 1
    logs = await _node_logs_for(db_session, task.id)
    assert logs[0].trigger_type is NodeLogTriggerType.FREEFORM_MANUAL
    assert logs[0].node_id is None
    assert fake.queries == ["привет из свободного поля"]


async def test_process_manual_queue_once_processes_fifo_by_requested_at(
    db_session: AsyncSession,
    tmp_path: Path,
    redis_client: Redis,
) -> None:
    task, user_id = await _make_task(db_session)
    await enqueue_freeform_prompt_run(
        db_session,
        task_id=task.id,
        raw_prompt_text="первый",
        requested_by=user_id,
    )
    await enqueue_freeform_prompt_run(
        db_session,
        task_id=task.id,
        raw_prompt_text="второй",
        requested_by=user_id,
    )
    fake = FakeClaudeAgentClient(
        messages_per_query=[[make_result_message()], [make_result_message()]],
    )
    session = ClaudeCodeSession(fake)

    processed = await process_manual_queue_once(
        db_session,
        task=task,
        claude_session=session,
        repos_path=tmp_path,
        redis_client=redis_client,
    )

    assert processed == 2
    assert fake.queries == ["первый", "второй"]


async def test_process_manual_queue_once_backs_off_when_lock_already_held(
    db_session: AsyncSession,
    tmp_path: Path,
    redis_client: Redis,
) -> None:
    task, user_id = await _make_task(db_session)
    await enqueue_freeform_prompt_run(
        db_session,
        task_id=task.id,
        raw_prompt_text="привет",
        requested_by=user_id,
    )
    session = ClaudeCodeSession(FakeClaudeAgentClient(messages_per_query=[[make_result_message()]]))

    async with acquire_task_operation_lock(
        redis_client,
        task_id=task.id,
        operation=MANUAL_QUEUE_LOCK_OPERATION,
    ):
        processed = await process_manual_queue_once(
            db_session,
            task=task,
            claude_session=session,
            repos_path=tmp_path,
            redis_client=redis_client,
        )

    assert processed == 0


async def test_expire_stale_manual_queue_requests_cancels_old_queued(
    db_session: AsyncSession,
) -> None:
    task, user_id = await _make_task(db_session)
    stale = await enqueue_freeform_prompt_run(
        db_session,
        task_id=task.id,
        raw_prompt_text="старый",
        requested_by=user_id,
    )
    stale.requested_at = datetime.now(UTC) - timedelta(hours=2)
    await db_session.flush()
    fresh = await enqueue_freeform_prompt_run(
        db_session,
        task_id=task.id,
        raw_prompt_text="свежий",
        requested_by=user_id,
    )

    expired_ids = await expire_stale_manual_queue_requests(
        db_session,
        older_than=datetime.now(UTC) - timedelta(hours=1),
    )

    assert expired_ids == [stale.id]
    assert stale.status is ManualRequestStatus.CANCELLED
    assert fresh.status is ManualRequestStatus.QUEUED


async def test_expire_stale_manual_queue_requests_ignores_non_queued(
    db_session: AsyncSession,
) -> None:
    task, user_id = await _make_task(db_session)
    request = await enqueue_freeform_prompt_run(
        db_session,
        task_id=task.id,
        raw_prompt_text="уже обработан",
        requested_by=user_id,
    )
    request.requested_at = datetime.now(UTC) - timedelta(hours=2)
    request.status = ManualRequestStatus.DONE
    await db_session.flush()

    expired_ids = await expire_stale_manual_queue_requests(
        db_session,
        older_than=datetime.now(UTC) - timedelta(hours=1),
    )

    assert expired_ids == []


async def _enqueue_library_run(
    db_session: AsyncSession,
) -> tuple[Task, TaskLibraryPrompt, TaskManualRequestQueue]:
    task, user_id = await _make_task(db_session)
    node = await _make_library_node(db_session)
    task_library_prompt = TaskLibraryPrompt(task_id=task.id, node_id=node.id, added_by=user_id)
    db_session.add(task_library_prompt)
    await db_session.flush()
    request = await enqueue_library_prompt_run(
        db_session,
        task_library_prompt=task_library_prompt,
        node=node,
        requested_by=user_id,
    )
    return task, task_library_prompt, request


async def test_library_prompt_is_marked_running_while_executing(
    db_session: AsyncSession,
    tmp_path: Path,
    redis_client: Redis,
) -> None:
    task, task_library_prompt, _request = await _enqueue_library_run(db_session)
    seen: list[LibraryPromptRunStatus] = []

    async def record_status() -> None:
        seen.append(task_library_prompt.last_run_status)

    fake = FakeClaudeAgentClient(
        messages_per_query=[[make_result_message()]],
        on_query=record_status,
    )

    await process_manual_queue_once(
        db_session,
        task=task,
        claude_session=ClaudeCodeSession(fake),
        repos_path=tmp_path,
        redis_client=redis_client,
    )

    assert seen == [LibraryPromptRunStatus.RUNNING]
    assert task_library_prompt.last_run_status is LibraryPromptRunStatus.SUCCESS


@pytest.mark.parametrize("stop_whole_task", [False, True])
async def test_stop_button_interrupts_running_library_prompt(
    db_session: AsyncSession,
    tmp_path: Path,
    redis_client: Redis,
    stop_whole_task: bool,
) -> None:
    """Раздел 7.3: ■ для running-промта; раздел 14.2: «Остановить» задачу
    прерывает и выполняющийся ручной запрос."""
    task, task_library_prompt, request = await _enqueue_library_run(db_session)
    fake = FakeClaudeAgentClient(messages_per_query=[[make_result_message()]])
    fake.message_delay_seconds = 30

    async def press_stop() -> None:
        await asyncio.sleep(0.3)
        if stop_whole_task:
            await request_task_control(redis_client, task.id, TaskControlCommand.STOP)
        else:
            await request_manual_stop(redis_client, task.id, request.id)
        fake.message_delay_seconds = 0

    presser = asyncio.ensure_future(press_stop())
    processed = await asyncio.wait_for(
        process_manual_queue_once(
            db_session,
            task=task,
            claude_session=ClaudeCodeSession(fake),
            repos_path=tmp_path,
            redis_client=redis_client,
        ),
        timeout=10,
    )
    await presser

    assert processed == 1
    assert fake.interrupted is True
    assert task_library_prompt.last_run_status is LibraryPromptRunStatus.STOPPED
    assert request.status is ManualRequestStatus.DONE
    logs = await _node_logs_for(db_session, task.id)
    assert [log.status for log in logs] == [NodeLogStatus.STOPPED]
    assert not await is_manual_stop_requested(redis_client, task.id, request.id)


async def test_stop_button_interrupts_running_freeform_prompt(
    db_session: AsyncSession,
    tmp_path: Path,
    redis_client: Redis,
) -> None:
    task, user_id = await _make_task(db_session)
    request = await enqueue_freeform_prompt_run(
        db_session,
        task_id=task.id,
        raw_prompt_text="долгий вопрос",
        requested_by=user_id,
    )
    fake = FakeClaudeAgentClient(messages_per_query=[[make_result_message()]])
    fake.message_delay_seconds = 30

    async def press_stop() -> None:
        await asyncio.sleep(0.3)
        await request_manual_stop(redis_client, task.id, request.id)
        fake.message_delay_seconds = 0

    presser = asyncio.ensure_future(press_stop())
    await asyncio.wait_for(
        process_manual_queue_once(
            db_session,
            task=task,
            claude_session=ClaudeCodeSession(fake),
            repos_path=tmp_path,
            redis_client=redis_client,
        ),
        timeout=10,
    )
    await presser

    logs = await _node_logs_for(db_session, task.id)
    assert [log.status for log in logs] == [NodeLogStatus.STOPPED]
