"""Ожидание сброса лимита LLM-аккаунтов — статус `awaiting_limit` (раздел 19.7 ТЗ)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import pytest

from db.models.enums import (
    LlmAccountStatus,
    ManualRequestStatus,
    ManualRequestType,
    NodeType,
    ScriptLanguage,
    TaskStatus,
)
from db.models.pipelines import Node, TaskNode
from db.models.prompts import TaskManualRequestQueue
from db.models.tasks import Task
from services import limit_wait
from services.crypto import encrypt
from services.errors import ConflictError
from services.library_commands import CommandSnapshot
from services.limit_wait import (
    author_waits_for_limit,
    check_limit_gate,
    enter_limit_wait,
    leave_limit_wait,
    limit_waits_to_resume,
    manual_request_node_type,
    pause_limit_wait,
    stop_limit_wait,
)
from services.llm_account_choice import LlmLimitWaitError
from services.notifications import NotificationEvent
from tests.factories import make_llm_account, make_pipeline, make_task, make_user

if TYPE_CHECKING:
    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncSession

    from tests.cliproxy_support import FakeCliproxy

_NOW = datetime.now(UTC)
_UNTIL = _NOW + timedelta(hours=2)


@pytest.fixture
def pushes(monkeypatch: pytest.MonkeyPatch) -> list[tuple[NotificationEvent, uuid.UUID, str]]:
    sent: list[tuple[NotificationEvent, uuid.UUID, str]] = []

    async def record(
        _db: AsyncSession, *, event: NotificationEvent, task: Task, **kwargs: Any
    ) -> None:
        sent.append((event, task.id, kwargs.get("detail", "")))

    monkeypatch.setattr(limit_wait, "notify_task_event", record)
    return sent


async def _task(db_session: AsyncSession, status: TaskStatus, **fields: Any) -> Task:
    return await make_task(db_session, status=status, **fields)


async def _waiting(
    db_session: AsyncSession,
    from_status: TaskStatus,
    *,
    order_index: int | None = 3,
    until: datetime = _UNTIL,
    created_by: uuid.UUID | None = None,
) -> Task:
    return await _task(
        db_session,
        TaskStatus.AWAITING_LIMIT,
        limit_wait_from_status=from_status,
        limit_wait_until=until,
        limit_wait_order_index=order_index,
        created_by=created_by,
    )


class TestEnterLimitWait:
    @pytest.mark.parametrize(
        ("status", "paused", "expected_from", "order_index"),
        [
            (TaskStatus.IN_PROGRESS, False, TaskStatus.IN_PROGRESS, 0),
            (TaskStatus.IN_PROGRESS, True, TaskStatus.PAUSED, 0),
            (TaskStatus.REBASE_CONFLICT, True, TaskStatus.PAUSED, 0),
            (TaskStatus.PAUSED, False, TaskStatus.PAUSED, 0),
            (TaskStatus.REFINING, True, TaskStatus.REFINING, None),
        ],
    )
    async def test_entered(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        pushes: list[tuple[NotificationEvent, uuid.UUID, str]],
        status: TaskStatus,
        paused: bool,
        expected_from: TaskStatus,
        order_index: int | None,
    ) -> None:
        task = await _task(db_session, status)

        entered = await enter_limit_wait(
            db_session,
            task=task,
            until=_UNTIL,
            redis_client=redis_client,
            paused=paused,
        )

        assert entered is True
        assert task.status is TaskStatus.AWAITING_LIMIT
        assert (task.limit_wait_from_status, task.limit_wait_until) == (expected_from, _UNTIL)
        assert task.limit_wait_order_index == order_index
        assert [(event, task_id) for event, task_id, _ in pushes] == [
            (NotificationEvent.LLM_LIMIT_WAIT, task.id),
        ]
        assert "МСК" in pushes[0][2]

    @pytest.mark.parametrize("status", [TaskStatus.FAILED, TaskStatus.PLAN_REVIEW])
    async def test_other_status_untouched(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        pushes: list[tuple[NotificationEvent, uuid.UUID, str]],
        status: TaskStatus,
    ) -> None:
        task = await _task(db_session, status)

        entered = await enter_limit_wait(
            db_session,
            task=task,
            until=_UNTIL,
            redis_client=redis_client,
        )

        assert (entered, task.status, pushes) == (False, status, [])

    async def test_notified_once_per_wait(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        pushes: list[tuple[NotificationEvent, uuid.UUID, str]],
    ) -> None:
        task = await _task(db_session, TaskStatus.IN_PROGRESS)
        await enter_limit_wait(db_session, task=task, until=_UNTIL, redis_client=redis_client)
        await leave_limit_wait(db_session, task=task)

        await enter_limit_wait(db_session, task=task, until=_UNTIL, redis_client=redis_client)

        assert len(pushes) == 1


class TestLeaveLimitWait:
    @pytest.mark.parametrize(
        "from_status",
        [
            TaskStatus.IN_PROGRESS,
            TaskStatus.PAUSED,
            TaskStatus.REBASE_CONFLICT,
            TaskStatus.REFINING,
        ],
    )
    async def test_back_to_previous_status(
        self,
        db_session: AsyncSession,
        from_status: TaskStatus,
    ) -> None:
        task = await _waiting(db_session, from_status)

        resume = await leave_limit_wait(db_session, task=task)

        assert resume is not None
        assert (resume.status, resume.order_index) == (from_status, 3)
        assert task.status is from_status
        assert (task.limit_wait_from_status, task.limit_wait_until) == (None, None)
        assert task.limit_wait_order_index is None

    async def test_redelivery(self, db_session: AsyncSession) -> None:
        task = await _waiting(db_session, TaskStatus.IN_PROGRESS)
        await leave_limit_wait(db_session, task=task)

        assert await leave_limit_wait(db_session, task=task) is None
        assert task.status is TaskStatus.IN_PROGRESS


class TestStopLimitWait:
    @pytest.mark.parametrize(
        ("from_status", "status", "restart"),
        [
            (TaskStatus.IN_PROGRESS, TaskStatus.FAILED, 3),
            (TaskStatus.PAUSED, TaskStatus.FAILED, 3),
            (TaskStatus.REFINING, TaskStatus.REFINING, None),
        ],
    )
    async def test_stopped(
        self,
        db_session: AsyncSession,
        from_status: TaskStatus,
        status: TaskStatus,
        restart: int | None,
    ) -> None:
        task = await _waiting(
            db_session,
            from_status,
            order_index=None if from_status is TaskStatus.REFINING else 3,
        )

        stopped = await stop_limit_wait(db_session, task=task)

        assert (stopped.status, stopped.last_failed_order_index) == (status, restart)
        assert stopped.limit_wait_from_status is None

    async def test_race_with_resume(self, db_session: AsyncSession) -> None:
        task = await _waiting(db_session, TaskStatus.IN_PROGRESS)
        stale = Task(
            id=task.id,
            status=TaskStatus.AWAITING_LIMIT,
            limit_wait_from_status=TaskStatus.IN_PROGRESS,
            limit_wait_order_index=3,
        )
        await leave_limit_wait(db_session, task=task)

        with pytest.raises(ConflictError):
            await stop_limit_wait(db_session, task=stale)


class TestPauseLimitWait:
    @pytest.mark.parametrize(
        ("from_status", "paused"),
        [
            (TaskStatus.IN_PROGRESS, True),
            (TaskStatus.REBASE_CONFLICT, True),
            (TaskStatus.PAUSED, False),
            (TaskStatus.REFINING, False),
        ],
    )
    async def test_pause(
        self,
        db_session: AsyncSession,
        from_status: TaskStatus,
        paused: bool,
    ) -> None:
        task = await _waiting(db_session, from_status)

        assert await pause_limit_wait(db_session, task_id=task.id) is paused
        await db_session.refresh(task)
        assert task.limit_wait_from_status is (TaskStatus.PAUSED if paused else from_status)
        assert task.status is TaskStatus.AWAITING_LIMIT


class TestAuthorWaits:
    async def test_nearest_reset(self, db_session: AsyncSession) -> None:
        user_id = (await make_user(db_session)).id
        await _waiting(db_session, TaskStatus.IN_PROGRESS, created_by=user_id)
        await _waiting(
            db_session,
            TaskStatus.PAUSED,
            until=_NOW + timedelta(hours=1),
            created_by=user_id,
        )
        await _waiting(db_session, TaskStatus.IN_PROGRESS, until=_NOW)

        assert await author_waits_for_limit(db_session, user_id) == _NOW + timedelta(hours=1)
        assert await author_waits_for_limit(db_session, uuid.uuid4()) is None


class TestLimitWaitsToResume:
    @pytest.mark.parametrize(
        ("until", "usage", "status", "resumed"),
        [
            (_NOW - timedelta(minutes=1), "95", LlmAccountStatus.ACTIVE, True),
            (_UNTIL, "95", LlmAccountStatus.ACTIVE, False),
            (_UNTIL, "10", LlmAccountStatus.ACTIVE, True),
            (_UNTIL, "10", LlmAccountStatus.DISABLED, True),
        ],
        ids=["reset_due", "still_waiting", "account_freed", "no_account_left"],
    )
    async def test_selected(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        fake_cliproxy: FakeCliproxy,
        until: datetime,
        usage: str,
        status: LlmAccountStatus,
        resumed: bool,
    ) -> None:
        user_id = (await make_user(db_session)).id
        account = await make_llm_account(db_session, owner_id=user_id, status=status)
        account.usage_5h_pct = Decimal(usage)
        account.usage_5h_resets_at = _UNTIL
        account.usage_checked_at = _NOW
        task = await _waiting(db_session, TaskStatus.IN_PROGRESS, until=until, created_by=user_id)
        await _task(db_session, TaskStatus.IN_PROGRESS)

        selected = await limit_waits_to_resume(
            db_session,
            redis_client=redis_client,
            cliproxy=fake_cliproxy.client(),
            now=_NOW,
        )

        assert selected == ([task.id] if resumed else [])


class _RecordingGate:
    """Ворота, которые всегда ждут сброса и запоминают тип хода."""

    def __init__(self) -> None:
        self.asked: list[NodeType | None] = []

    async def __call__(self, *, node_type: NodeType | None = None) -> datetime | None:
        self.asked.append(node_type)
        return _UNTIL


class TestCheckLimitGate:
    @pytest.mark.parametrize(
        "node_type",
        [NodeType.PLAIN_PROMPT, NodeType.SLASH_COMMAND, NodeType.PLAN_PROMPT],
    )
    async def test_model_turn_waits(self, node_type: NodeType) -> None:
        gate = _RecordingGate()

        with pytest.raises(LlmLimitWaitError) as raised:
            await check_limit_gate(gate, node_type=node_type)

        assert (raised.value.until, gate.asked) == (_UNTIL, [node_type])

    @pytest.mark.parametrize("node_type", [NodeType.SCRIPT, NodeType.CLEAR_CONTEXT])
    async def test_no_model_turn_skipped(self, node_type: NodeType) -> None:
        gate = _RecordingGate()

        await check_limit_gate(gate, node_type=node_type)

        assert gate.asked == []


async def _add_waiting_node(
    db_session: AsyncSession,
    task: Task,
    node_type: NodeType,
) -> Node:
    pipeline = await make_pipeline(db_session, created_by=task.created_by)
    node = Node(
        created_by=task.created_by,
        pipeline_id=pipeline.id,
        order_index=3,
        name="waiting",
        node_type=node_type,
        prompt_template="план",
        timeout_seconds=60,
        max_retries=1,
        retry_base_delay_seconds=0,
        is_skipped=False,
        is_library_item=False,
        is_archived=False,
    )
    db_session.add(node)
    await db_session.flush()
    db_session.add(TaskNode(task_id=task.id, node_id=node.id, order_index=3))
    await db_session.flush()
    return node


class TestResumeByTurnType:
    """Аккаунт без план-режима свободен — продолжает только ход, которому он годится."""

    @pytest.mark.parametrize(
        ("from_status", "node_type", "queued_freeform", "resumed"),
        [
            (TaskStatus.IN_PROGRESS, NodeType.PLAN_PROMPT, False, False),
            (TaskStatus.IN_PROGRESS, NodeType.PLAIN_PROMPT, False, True),
            (TaskStatus.IN_PROGRESS, NodeType.PLAN_PROMPT, True, True),
            (TaskStatus.REBASE_CONFLICT, NodeType.PLAN_PROMPT, False, True),
        ],
        ids=["plan_waits", "plain_resumes", "queued_request_first", "rebase_first"],
    )
    async def test_selected(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        fake_cliproxy: FakeCliproxy,
        from_status: TaskStatus,
        node_type: NodeType,
        queued_freeform: bool,
        resumed: bool,
    ) -> None:
        user_id = (await make_user(db_session)).id
        claude = await make_llm_account(db_session, owner_id=user_id)
        claude.usage_5h_pct = Decimal("95")
        claude.usage_5h_resets_at = _UNTIL
        claude.usage_checked_at = _NOW
        await make_llm_account(
            db_session,
            owner_id=user_id,
            provider="xai",
            default_model="grok-5",
            label="grok",
        )
        task = await _waiting(db_session, from_status, created_by=user_id)
        await _add_waiting_node(db_session, task, node_type)
        if queued_freeform:
            db_session.add(
                TaskManualRequestQueue(
                    task_id=task.id,
                    request_type=ManualRequestType.FREEFORM_PROMPT,
                    raw_prompt_text="вопрос",
                    requested_by=user_id,
                    status=ManualRequestStatus.QUEUED,
                    requested_at=_NOW,
                ),
            )
            await db_session.flush()

        selected = await limit_waits_to_resume(
            db_session,
            redis_client=redis_client,
            cliproxy=fake_cliproxy.client(),
            now=_NOW,
        )

        assert selected == ([task.id] if resumed else [])


def _snapshot(node_type: NodeType) -> str:
    return encrypt(
        CommandSnapshot(
            invocation="/run",
            raw_arguments="",
            arguments=[],
            name="run",
            node_type=node_type,
            prompt_template=None,
            script_language=ScriptLanguage.BASH,
            script_content="echo ok",
            docker_image=None,
            llm_output_last_n=None,
            reasoning_effort=None,
        ).model_dump_json(),
    )


class TestManualRequestNodeType:
    @pytest.mark.parametrize(
        ("request_type", "node_type", "snapshot_type", "expected"),
        [
            (ManualRequestType.FREEFORM_PROMPT, None, None, NodeType.PLAIN_PROMPT),
            (ManualRequestType.PARENT_SUMMARY, None, None, NodeType.PLAIN_PROMPT),
            (ManualRequestType.LIBRARY_PROMPT, NodeType.SCRIPT, None, NodeType.SCRIPT),
            (ManualRequestType.LIBRARY_PROMPT, NodeType.PLAN_PROMPT, None, NodeType.PLAN_PROMPT),
            (
                ManualRequestType.LIBRARY_PROMPT,
                NodeType.PLAIN_PROMPT,
                NodeType.SCRIPT,
                NodeType.SCRIPT,
            ),
        ],
        ids=["freeform", "parent_summary", "library_script", "library_plan", "command_snapshot"],
    )
    async def test_type(
        self,
        db_session: AsyncSession,
        request_type: ManualRequestType,
        node_type: NodeType | None,
        snapshot_type: NodeType | None,
        expected: NodeType,
    ) -> None:
        """Команда библиотеки выполняется по снимку: тип — из него, а не из текущей ноды."""
        task = await _task(db_session, TaskStatus.IN_PROGRESS)
        node = None if node_type is None else await _add_waiting_node(db_session, task, node_type)
        request = TaskManualRequestQueue(
            task_id=task.id,
            request_type=request_type,
            node_id=None if node is None else node.id,
            raw_prompt_text="вопрос" if node is None else None,
            requested_by=task.created_by,
            status=ManualRequestStatus.QUEUED,
            requested_at=_NOW,
            command_snapshot_encrypted=None if snapshot_type is None else _snapshot(snapshot_type),
        )

        assert await manual_request_node_type(db_session, request) is expected
