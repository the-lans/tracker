"""
Саммари родительской задачи при старте дочерней (`services/parent_summary.py`,
`tasks/session_worker.py`; раздел 3.1 ТЗ, решение 2026-10-20).
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

import pytest
import sqlalchemy as sa
from claude_agent_sdk import AssistantMessage, TextBlock

from clients.claude_agent import ClaudeCodeSession
from db.models.enums import (
    ManualRequestStatus,
    NodeLogStatus,
    NodeLogTriggerType,
    NodeType,
    ParentSummaryStatus,
    TaskStatus,
    UserRole,
)
from db.models.logs import NodeLog
from db.models.pipelines import Node, Pipeline, TaskNode
from db.models.prompts import TaskManualRequestQueue
from db.models.tasks import Task, TaskParentSummary
from db.models.users import User
from services.manual_queue import process_manual_queue_once
from services.parent_summary import deny_all_tools
from services.task_control import TaskControlCommand, request_task_control
from tasks import session_worker
from tests.fakes import FakeClaudeAgentClient, make_result_message

if TYPE_CHECKING:
    from claude_agent_sdk import Message
    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncSession

    from tests.worker_support import WorkerEnv

_SUMMARY = "Родитель сделал авторизацию, осталось покрыть тестами."
_SUMMARY_PROMPT_START = "Кратко перескажи историю этой задачи"
_DELIVERY_START = "Контекст родительской задачи"


def _answer(text: str) -> list[Message]:
    return [AssistantMessage(content=[TextBlock(text=text)], model="claude"), make_result_message()]


async def _make_user(db_session: AsyncSession) -> User:
    user = User(email=f"{uuid.uuid4()}@example.com", role=UserRole.USER)
    db_session.add(user)
    await db_session.flush()
    return user


async def _make_parent(
    db_session: AsyncSession,
    user: User,
    *,
    status: TaskStatus,
    session_id: str | None,
) -> Task:
    parent = Task(
        code=f"RR-{uuid.uuid4().hex[:5]}",
        title="Родитель",
        description="d",
        created_by=user.id,
        status=status,
        session_id=session_id,
    )
    db_session.add(parent)
    await db_session.flush()
    return parent


async def _make_child(db_session: AsyncSession, user: User, parent: Task) -> Task:
    pipeline = Pipeline(name="p", is_archived=False)
    db_session.add(pipeline)
    await db_session.flush()
    child = Task(
        code=f"RR-{uuid.uuid4().hex[:5]}",
        title="Дочерняя",
        description="d",
        created_by=user.id,
        pipeline_id=pipeline.id,
        parent_task_id=parent.id,
        use_parent_summary=True,
        status=TaskStatus.QUEUED,
    )
    db_session.add(child)
    await db_session.flush()
    node = Node(
        pipeline_id=pipeline.id,
        order_index=0,
        name="node-0",
        node_type=NodeType.PLAIN_PROMPT,
        prompt_template="шаг 0",
        timeout_seconds=60,
        max_retries=1,
        retry_base_delay_seconds=0,
        is_skipped=False,
        is_library_item=False,
        is_archived=False,
    )
    db_session.add(node)
    await db_session.flush()
    db_session.add(TaskNode(task_id=child.id, node_id=node.id, order_index=0))
    await db_session.flush()
    return child


async def _run_child(child: Task, **kwargs: Any) -> None:
    await session_worker._run_task_session_async(
        child.id,
        start_after_order_index=kwargs.get("start_after_order_index"),
        continuation=False,
    )


async def _logs(db_session: AsyncSession, task: Task) -> list[NodeLog]:
    stmt = sa.select(NodeLog).where(NodeLog.task_id == task.id).order_by(NodeLog.started_at)
    return list((await db_session.execute(stmt)).scalars().all())


async def _status_of(db_session: AsyncSession, task: Task) -> TaskStatus:
    await db_session.refresh(task)
    return task.status


async def _summary_of(db_session: AsyncSession, child: Task) -> TaskParentSummary:
    summary = await db_session.scalar(
        sa.select(TaskParentSummary).where(TaskParentSummary.child_task_id == child.id),
    )
    assert summary is not None
    await db_session.refresh(summary)
    return summary


class TestBusyParent:
    async def test_queued_summary_delivered(
        self,
        db_session: AsyncSession,
        worker_env: WorkerEnv,
        redis_client: Redis,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        user = await _make_user(db_session)
        parent = await _make_parent(
            db_session,
            user,
            status=TaskStatus.IN_PROGRESS,
            session_id="sess-parent",
        )
        child = await _make_child(db_session, user, parent)
        parent_client = FakeClaudeAgentClient(messages_per_query=[_answer(_SUMMARY)])

        async def parent_worker_takes_queue(*_args: Any, **_kwargs: Any) -> bool:
            # Пока дочерняя ждёт, воркер родителя доходит до своей очереди.
            await process_manual_queue_once(
                db_session,
                task=parent,
                claude_session=ClaudeCodeSession(parent_client),
                repos_path=worker_env.repos_root,
                redis_client=redis_client,
            )
            return True

        monkeypatch.setattr(
            "services.parent_summary.wait_for_task_signal",
            parent_worker_takes_queue,
        )
        worker_env.client = FakeClaudeAgentClient(
            messages_per_query=[_answer("Принято"), [make_result_message()]],
        )

        await _run_child(child)

        assert parent_client.queries[0].startswith(_SUMMARY_PROMPT_START)
        [parent_log] = await _logs(db_session, parent)
        assert parent_log.trigger_type is NodeLogTriggerType.SUMMARY_FOR_CHILD
        assert parent_log.llm_output_text == _SUMMARY
        delivery, step = worker_env.client.queries
        assert delivery.startswith(_DELIVERY_START)
        assert _SUMMARY in delivery
        assert step == "шаг 0"
        child_logs = await _logs(db_session, child)
        assert child_logs[0].trigger_type is NodeLogTriggerType.PARENT_SUMMARY
        assert child_logs[0].status is NodeLogStatus.SUCCESS
        summary = await _summary_of(db_session, child)
        assert summary.status is ParentSummaryStatus.READY
        assert summary.delivered_at is not None
        await db_session.refresh(parent)
        assert parent.status is TaskStatus.IN_PROGRESS

    async def test_expired_request_falls_back_to_fork(
        self,
        db_session: AsyncSession,
        worker_env: WorkerEnv,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        user = await _make_user(db_session)
        parent = await _make_parent(
            db_session,
            user,
            status=TaskStatus.IN_PROGRESS,
            session_id="sess-parent",
        )
        child = await _make_child(db_session, user, parent)

        async def request_expires(*_args: Any, **_kwargs: Any) -> bool:
            request = await db_session.scalar(
                sa.select(TaskManualRequestQueue).where(
                    TaskManualRequestQueue.task_id == parent.id,
                ),
            )
            assert request is not None
            request.status = ManualRequestStatus.CANCELLED
            await db_session.commit()
            return True

        monkeypatch.setattr("services.parent_summary.wait_for_task_signal", request_expires)
        fork_client = FakeClaudeAgentClient(messages_per_query=[_answer(_SUMMARY)])
        worker_env.queued_clients = [fork_client]
        worker_env.client = FakeClaudeAgentClient(
            messages_per_query=[_answer("Принято"), [make_result_message()]],
        )

        await _run_child(child)

        assert worker_env.options[0].fork_session is True
        assert _SUMMARY in worker_env.client.queries[0]

    async def test_stop_while_waiting_fails_child(
        self,
        db_session: AsyncSession,
        worker_env: WorkerEnv,
        redis_client: Redis,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        user = await _make_user(db_session)
        parent = await _make_parent(
            db_session,
            user,
            status=TaskStatus.PAUSED,
            session_id="sess-parent",
        )
        child = await _make_child(db_session, user, parent)

        async def user_presses_stop(*_args: Any, **_kwargs: Any) -> bool:
            await request_task_control(redis_client, child.id, TaskControlCommand.STOP)
            return True

        monkeypatch.setattr("services.parent_summary.wait_for_task_signal", user_presses_stop)

        await _run_child(child)

        await db_session.refresh(child)
        assert child.status is TaskStatus.FAILED
        assert child.last_failed_order_index == 0
        assert worker_env.client.connected is False


class TestIdleParent:
    async def test_fork_of_parent_session(
        self,
        db_session: AsyncSession,
        worker_env: WorkerEnv,
    ) -> None:
        user = await _make_user(db_session)
        parent = await _make_parent(
            db_session,
            user,
            status=TaskStatus.DONE,
            session_id="sess-parent",
        )
        child = await _make_child(db_session, user, parent)
        fork_client = FakeClaudeAgentClient(messages_per_query=[_answer(_SUMMARY)])
        worker_env.queued_clients = [fork_client]
        worker_env.client = FakeClaudeAgentClient(
            messages_per_query=[_answer("Принято"), [make_result_message()]],
        )

        await _run_child(child)

        fork_options = worker_env.options[0]
        assert fork_options.fork_session is True
        assert fork_options.resume == "sess-parent"
        assert fork_options.cwd == str(worker_env.repos_root / parent.code)
        assert fork_options.can_use_tool is deny_all_tools
        assert fork_options.mcp_servers == {}
        assert fork_client.disconnected is True
        assert _SUMMARY in worker_env.client.queries[0]
        [parent_log] = await _logs(db_session, parent)
        assert parent_log.trigger_type is NodeLogTriggerType.SUMMARY_FOR_CHILD
        await db_session.refresh(child)
        assert child.status is TaskStatus.DONE

    async def test_no_session_note(
        self,
        db_session: AsyncSession,
        worker_env: WorkerEnv,
    ) -> None:
        user = await _make_user(db_session)
        parent = await _make_parent(db_session, user, status=TaskStatus.NEW, session_id=None)
        child = await _make_child(db_session, user, parent)
        worker_env.client = FakeClaudeAgentClient(messages_per_query=[[make_result_message()]])

        await _run_child(child)

        assert worker_env.client.queries == ["шаг 0"]
        [note, _step] = await _logs(db_session, child)
        assert note.trigger_type is NodeLogTriggerType.PARENT_SUMMARY
        assert note.status is NodeLogStatus.FAILED
        assert note.rendered_prompt is not None
        assert "недоступно" in note.rendered_prompt
        summary = await _summary_of(db_session, child)
        assert summary.status is ParentSummaryStatus.UNAVAILABLE


class TestRestart:
    async def test_delivered_summary_not_repeated(
        self,
        db_session: AsyncSession,
        worker_env: WorkerEnv,
    ) -> None:
        user = await _make_user(db_session)
        parent = await _make_parent(
            db_session,
            user,
            status=TaskStatus.DONE,
            session_id="sess-parent",
        )
        child = await _make_child(db_session, user, parent)
        worker_env.queued_clients = [FakeClaudeAgentClient(messages_per_query=[_answer(_SUMMARY)])]
        worker_env.client = FakeClaudeAgentClient(
            messages_per_query=[_answer("Принято"), [make_result_message(is_error=True)]],
        )
        await _run_child(child)
        assert await _status_of(db_session, child) is TaskStatus.FAILED

        worker_env.client = FakeClaudeAgentClient(messages_per_query=[[make_result_message()]])
        await _run_child(child, start_after_order_index=-1)

        assert worker_env.client.queries == ["шаг 0"]
        assert await _status_of(db_session, child) is TaskStatus.DONE
