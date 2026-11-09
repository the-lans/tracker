"""
Конкурентные отмена, захват очереди и завершение задачи на независимых соединениях.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
import sqlalchemy as sa
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import services.manual_queue as queue
import tasks.session_worker as worker
from clients.claude_agent import ClaudeCodeSession
from db.base import Base
from db.models.enums import ManualRequestStatus, NodeType, ScriptLanguage, TaskStatus
from db.models.logs import NodeLog
from db.models.pipelines import Node
from db.models.prompts import TaskManualRequestQueue
from db.models.tasks import Task
from services.errors import ConflictError
from services.library_commands import enqueue_command
from services.manual_admission import close_manual_requests
from services.parent_summary import get_or_request_parent_summary, wait_for_parent_summary
from services.pipeline_orchestrator import PipelineRunOutcome
from services.plan_mode import ActiveNodeContext
from services.system_settings import resolve_node_execution_defaults, resolve_runner_image
from services.task_status import reset_task_run
from tests.factories import make_task, make_user
from tests.fakes import FakeClaudeAgentClient


@pytest_asyncio.fixture
async def command_sessions(
    scratch_database: str,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(scratch_database)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def queued_command(
    command_sessions: async_sessionmaker[AsyncSession],
) -> tuple[uuid.UUID, uuid.UUID]:
    async with command_sessions() as session:
        owner = await make_user(session)
        task = await make_task(session, created_by=owner.id, status=TaskStatus.IN_PROGRESS)
        session.add(
            Node(
                created_by=owner.id,
                name="Script",
                description="test",
                is_library_item=True,
                slash_name="test",
                node_type=NodeType.SCRIPT,
                script_language=ScriptLanguage.PYTHON,
                script_content="print('ACCEPTED_EXECUTED')",
            )
        )
        await session.commit()
        row = await enqueue_command(
            session,
            task=task,
            requested_by=owner.id,
            invocation="/test",
            client_request_id=uuid.uuid4(),
        )
        return task.id, row.id


class TestQueueClaim:
    async def test_cancelled_row_is_not_executed(
        self,
        command_sessions: async_sessionmaker[AsyncSession],
        queued_command: tuple[uuid.UUID, uuid.UUID],
        redis_client: Redis,
        tmp_path: Path,
    ) -> None:
        task_id, request_id = queued_command
        async with command_sessions() as processing, command_sessions() as cancelling:
            stale = await processing.get(TaskManualRequestQueue, request_id)
            task = await processing.get(Task, task_id)
            fresh = await cancelling.get(TaskManualRequestQueue, request_id)
            assert stale and fresh and task
            await queue.cancel_manual_request(cancelling, fresh)
            await queue._process_single_request(
                processing,
                task=task,
                request=stale,
                claude_session=ClaudeCodeSession(FakeClaudeAgentClient(messages_per_query=[])),
                repos_path=tmp_path,
                redis_client=redis_client,
                active_node_context=None,
            )
            assert stale.status == ManualRequestStatus.CANCELLED
            assert await processing.scalar(sa.select(sa.func.count()).select_from(NodeLog)) == 0

    async def test_stale_cancel_cannot_overwrite_claim(
        self,
        command_sessions: async_sessionmaker[AsyncSession],
        queued_command: tuple[uuid.UUID, uuid.UUID],
        redis_client: Redis,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        task_id, request_id = queued_command
        started, finish = asyncio.Event(), asyncio.Event()

        async def blocked(*_args: object, **_kwargs: object) -> None:
            started.set()
            await finish.wait()

        monkeypatch.setattr(queue, "_run_library_prompt", blocked)
        async with command_sessions() as processing, command_sessions() as cancelling:
            stale = await cancelling.get(TaskManualRequestQueue, request_id)
            current = await processing.get(TaskManualRequestQueue, request_id)
            task = await processing.get(Task, task_id)
            assert stale and current and task
            running = asyncio.create_task(
                queue._process_single_request(
                    processing,
                    task=task,
                    request=current,
                    claude_session=ClaudeCodeSession(FakeClaudeAgentClient(messages_per_query=[])),
                    repos_path=tmp_path,
                    redis_client=redis_client,
                    active_node_context=None,
                )
            )
            try:
                await asyncio.wait_for(started.wait(), 5)
                with pytest.raises(ConflictError):
                    await queue.cancel_manual_request(cancelling, stale)
                assert stale.status == ManualRequestStatus.PROCESSING
            finally:
                finish.set()
                await asyncio.wait_for(running, 5)


class TestFinalization:
    async def test_drain_accepted_before_push(
        self,
        command_sessions: async_sessionmaker[AsyncSession],
        queued_command: tuple[uuid.UUID, uuid.UUID],
        redis_client: Redis,
        tmp_path: Path,
    ) -> None:
        task_id, request_id = queued_command
        async with command_sessions() as session:
            task = await session.get(Task, task_id)
            assert task
            fake = FakeClaudeAgentClient(messages_per_query=[])
            control = worker._SessionControl(
                db_session=session,
                task=task,
                claude_session=ClaudeCodeSession(fake),
                workspace=tmp_path,
                redis_client=redis_client,
                active_node_context=ActiveNodeContext(),
                bridge_client_factory=lambda _sid: fake,
                recovery_client_factory=lambda _sid: fake,
                has_llm=False,
            )
            await worker._run_connected_session(
                session, control=control, parent_summary=None, start_after_order_index=None
            )
            row = await session.get(TaskManualRequestQueue, request_id)
            assert task.manual_requests_closed and row and row.status == ManualRequestStatus.DONE
            log = (await session.scalars(sa.select(NodeLog))).one()
            assert log.script_stdout == "ACCEPTED_EXECUTED\n"

    async def test_push_rejects_new_commands(
        self,
        command_sessions: async_sessionmaker[AsyncSession],
        queued_command: tuple[uuid.UUID, uuid.UUID],
        redis_client: Redis,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        task_id, request_id = queued_command
        pushing, finish = asyncio.Event(), asyncio.Event()

        async def push(*_args: object, **_kwargs: object) -> None:
            pushing.set()
            await finish.wait()

        monkeypatch.setattr(worker, "push_task_workspace", push)
        monkeypatch.setattr("services.task_status.notify_task_event", AsyncMock())
        async with command_sessions() as settling, command_sessions() as submitting:
            request = await settling.get(TaskManualRequestQueue, request_id)
            task = await settling.get(Task, task_id)
            assert request and task
            await queue.cancel_manual_request(settling, request)
            completing = asyncio.create_task(
                worker._settle_pipeline_run(
                    settling,
                    task=task,
                    outcome=PipelineRunOutcome(completed=True),
                    rebase_resolved=True,
                    repos_root=tmp_path,
                    redis_client=redis_client,
                )
            )
            try:
                await asyncio.wait_for(pushing.wait(), 5)
                loaded = await submitting.get(Task, task_id)
                assert loaded
                with pytest.raises(ConflictError, match="приём"):
                    await enqueue_command(
                        submitting,
                        task=loaded,
                        requested_by=loaded.created_by,
                        invocation="/test",
                        client_request_id=uuid.uuid4(),
                    )
                await submitting.rollback()
            finally:
                finish.set()
                await asyncio.wait_for(completing, 5)
            await settling.refresh(task)
            assert task.status == TaskStatus.DONE

    async def test_idempotent_retry_after_close(
        self,
        command_sessions: async_sessionmaker[AsyncSession],
        queued_command: tuple[uuid.UUID, uuid.UUID],
    ) -> None:
        task_id, request_id = queued_command
        async with command_sessions() as session:
            task = await session.get(Task, task_id)
            request = await session.get(TaskManualRequestQueue, request_id)
            assert task and request and request.client_request_id
            client_id = request.client_request_id
            await close_manual_requests(session, task_id)
            repeated = await enqueue_command(
                session,
                task=task,
                requested_by=task.created_by,
                invocation="/test",
                client_request_id=client_id,
            )
            assert repeated.id == request_id


class TestAdmissionLifecycle:
    @pytest.mark.parametrize("status", [TaskStatus.FAILED, TaskStatus.DONE])
    async def test_reopens_on_new_run(
        self,
        command_sessions: async_sessionmaker[AsyncSession],
        queued_command: tuple[uuid.UUID, uuid.UUID],
        status: TaskStatus,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr("services.task_status.notify_task_event", AsyncMock())
        async with command_sessions() as session:
            task = await session.get(Task, queued_command[0])
            assert task
            task.status = status
            task.manual_requests_closed = True
            task.last_failed_order_index = 0
            await session.commit()
            if status is TaskStatus.FAILED:
                assert await worker._claim_task(session, task, continuation=False)
            else:
                await reset_task_run(session, task_id=task.id)
            await session.refresh(task)
            assert not task.manual_requests_closed

    async def test_parent_finishing_uses_fork_after_wait(
        self,
        command_sessions: async_sessionmaker[AsyncSession],
        redis_client: Redis,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        async with command_sessions() as session:
            owner = await make_user(session)
            parent = await make_task(
                session,
                created_by=owner.id,
                status=TaskStatus.IN_PROGRESS,
                session_id="parent-session",
                manual_requests_closed=True,
            )
            child = await make_task(
                session, created_by=owner.id, parent_task_id=parent.id, use_parent_summary=True
            )
            await session.commit()
            summary = await get_or_request_parent_summary(
                session, child=child, redis_client=redis_client
            )
            assert summary.manual_request_id is None
            assert (
                await session.scalar(sa.select(sa.func.count()).select_from(TaskManualRequestQueue))
                == 0
            )

            async def parent_finishes(*_args: object, **_kwargs: object) -> None:
                parent.status = TaskStatus.DONE
                await session.commit()

            wait = AsyncMock(side_effect=parent_finishes)
            monkeypatch.setattr("services.parent_summary.wait_for_task_signal", wait)
            assert await wait_for_parent_summary(
                session,
                summary=summary,
                redis_client=redis_client,
                is_stop_requested=AsyncMock(return_value=False),
            )
            wait.assert_awaited_once()


class TestAtomicConfigurationReads:
    async def test_default_reads_do_not_commit_caller(
        self,
        command_sessions: async_sessionmaker[AsyncSession],
        queued_command: tuple[uuid.UUID, uuid.UUID],
    ) -> None:
        async with command_sessions() as editing, command_sessions() as observer:
            task = await editing.get(Task, queued_command[0])
            request = await editing.get(TaskManualRequestQueue, queued_command[1])
            assert task and request
            node = await editing.get(Node, request.node_id)
            assert node
            task.manual_requests_closed = True
            assert await resolve_runner_image(editing, node) == "tracker-runner-python:latest"
            defaults = await resolve_node_execution_defaults(
                editing, timeout_seconds=None, max_retries=None, retry_base_delay_seconds=None
            )
            assert defaults.timeout_seconds == 600
            before_commit = await observer.get(Task, task.id)
            assert before_commit and not before_commit.manual_requests_closed
            await editing.rollback()
