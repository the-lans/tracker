"""
Чат с агентом в «Уточняется» (раздел 14.4 ТЗ): режим `chat_only` воркера
сессии и `services/refining_chat.py`.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import pytest
import sqlalchemy as sa
from claude_agent_sdk import PermissionResultAllow
from claude_agent_sdk.types import ToolPermissionContext

from clients.claude_agent import REMOTE_CONTROL_EXTRA_ARG
from db.models.enums import ManualRequestStatus, NodeLogStatus, TaskStatus
from db.models.logs import NodeLog
from db.models.prompts import TaskManualRequestQueue
from db.models.tasks import Task
from services import refining_chat
from services.autostart import find_tasks_due_for_autostart
from services.errors import ConflictError, ValidationError
from services.manual_admission import ensure_manual_requests_open
from services.manual_queue import enqueue_freeform_prompt_run, expire_stale_manual_queue_requests
from services.remote_control import check_session_bridges
from services.session_heartbeat import is_session_alive, keep_session_heartbeat
from tasks import session_worker
from tests.factories import make_llm_account, make_pipeline, make_task, make_user
from tests.fakes import FakeClaudeAgentClient, make_result_message, patch_plan_mode_signals

if TYPE_CHECKING:
    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncSession

    from tests.worker_support import WorkerEnv

_SESSION_ID = "sess-chat"


async def _refining_task(
    db_session: AsyncSession,
    *,
    status: TaskStatus = TaskStatus.REFINING,
    session_id: str | None = None,
) -> Task:
    user = await make_user(db_session)
    pipeline = await make_pipeline(db_session, created_by=user.id)
    account = await make_llm_account(db_session, owner_id=user.id)
    task = await make_task(
        db_session,
        created_by=user.id,
        pipeline_id=pipeline.id,
        status=status,
        llm_account_id=account.id,
        session_id=session_id,
    )
    await db_session.commit()
    return task


async def _enqueue(db_session: AsyncSession, task: Task, text: str) -> None:
    await enqueue_freeform_prompt_run(
        db_session,
        task_id=task.id,
        raw_prompt_text=text,
        requested_by=task.created_by,
    )


async def _request_statuses(db_session: AsyncSession, task: Task) -> list[ManualRequestStatus]:
    rows = await db_session.scalars(
        sa.select(TaskManualRequestQueue.status)
        .where(TaskManualRequestQueue.task_id == task.id)
        .order_by(TaskManualRequestQueue.requested_at),
    )
    return list(rows)


async def _run_chat(task: Task) -> None:
    await session_worker._run_task_session_async(
        task.id,
        start_after_order_index=None,
        continuation=False,
        chat_only=True,
    )


@pytest.fixture
def followups(monkeypatch: pytest.MonkeyPatch) -> list[tuple[Any, ...]]:
    calls: list[tuple[Any, ...]] = []

    def record(*args: Any, **kwargs: Any) -> None:
        calls.append((args, kwargs))

    monkeypatch.setattr(session_worker.run_task_session, "delay", record)
    return calls


def _answers(count: int) -> list[list[Any]]:
    return [[make_result_message(session_id=_SESSION_ID)] for _ in range(count)]


class TestChatWorker:
    async def test_runs_queue_without_pipeline(
        self,
        db_session: AsyncSession,
        worker_env: WorkerEnv,
        redis_client: Redis,
        followups: list[tuple[Any, ...]],
    ) -> None:
        task = await _refining_task(db_session)
        await _enqueue(db_session, task, "первый вопрос")
        await _enqueue(db_session, task, "второй вопрос")
        worker_env.client = FakeClaudeAgentClient(messages_per_query=_answers(2))

        await _run_chat(task)

        await db_session.refresh(task)
        assert worker_env.client.queries == ["первый вопрос", "второй вопрос"]
        assert (task.status, task.session_id) == (TaskStatus.REFINING, _SESSION_ID)
        assert (task.chat_active, task.launched_manually) == (False, True)
        assert await _request_statuses(db_session, task) == [ManualRequestStatus.DONE] * 2
        assert worker_env.client.disconnected is True
        assert not await is_session_alive(redis_client, task.id)
        assert followups == []

    async def test_resumes_existing_session(
        self,
        db_session: AsyncSession,
        worker_env: WorkerEnv,
        followups: list[tuple[Any, ...]],
    ) -> None:
        task = await _refining_task(db_session, session_id="sess-earlier")
        await _enqueue(db_session, task, "продолжим")
        worker_env.client = FakeClaudeAgentClient(messages_per_query=_answers(1))

        await _run_chat(task)

        options = worker_env.options[0]
        assert options.resume == "sess-earlier"
        assert REMOTE_CONTROL_EXTRA_ARG not in options.extra_args

    async def test_question_returns_to_refining(
        self,
        db_session: AsyncSession,
        worker_env: WorkerEnv,
        monkeypatch: pytest.MonkeyPatch,
        followups: list[tuple[Any, ...]],
    ) -> None:
        task = await _refining_task(db_session)
        await _enqueue(db_session, task, "уточни")
        statuses_while_asking: list[TaskStatus] = []
        answers: list[str] = []

        async def user_answers(*, timeout: float | None) -> bool:
            await db_session.refresh(task)
            statuses_while_asking.append(task.status)
            pending = await db_session.scalar(
                sa.select(NodeLog).where(NodeLog.status == NodeLogStatus.AWAITING_DECISION),
            )
            assert pending is not None
            pending.user_input_text = "0"
            await db_session.commit()
            return True

        patch_plan_mode_signals(monkeypatch, user_answers)

        async def agent_asks() -> None:
            can_use_tool = worker_env.options[0].can_use_tool
            assert can_use_tool is not None
            question = {
                "question": "Какую базу?",
                "header": "База",
                "options": [{"label": "main"}, {"label": "dev"}],
                "multiSelect": False,
            }
            result = await can_use_tool(
                "AskUserQuestion",
                {"questions": [question]},
                ToolPermissionContext(),
            )
            assert isinstance(result, PermissionResultAllow)
            assert result.updated_input is not None
            answers.append(result.updated_input["answers"]["Какую базу?"])

        worker_env.client = FakeClaudeAgentClient(
            messages_per_query=_answers(1),
            on_query=agent_asks,
        )

        await _run_chat(task)

        await db_session.refresh(task)
        assert statuses_while_asking == [TaskStatus.AWAITING_INPUT]
        assert answers == ["main"]
        assert (task.status, task.chat_active) == (TaskStatus.REFINING, False)

    async def test_crash_keeps_refining(
        self,
        db_session: AsyncSession,
        worker_env: WorkerEnv,
        followups: list[tuple[Any, ...]],
    ) -> None:
        task = await _refining_task(db_session)
        await _enqueue(db_session, task, "вопрос")

        async def sdk_crashes() -> None:
            raise RuntimeError("процесс claude упал")

        worker_env.client.connect = sdk_crashes  # type: ignore[method-assign]

        await _run_chat(task)

        await db_session.refresh(task)
        assert (task.status, task.chat_active) == (TaskStatus.REFINING, False)
        # Цикла падений нет: оставшийся запрос ждёт следующего сообщения.
        assert followups == []

    async def test_message_after_queue_gets_followup(
        self,
        db_session: AsyncSession,
        worker_env: WorkerEnv,
        followups: list[tuple[Any, ...]],
    ) -> None:
        task = await _refining_task(db_session)
        await _enqueue(db_session, task, "вопрос")
        worker_env.client = FakeClaudeAgentClient(messages_per_query=_answers(1))
        disconnect = worker_env.client.disconnect

        async def user_writes_while_leaving() -> None:
            await disconnect()
            await _enqueue(db_session, task, "ещё вопрос")

        worker_env.client.disconnect = user_writes_while_leaving  # type: ignore[method-assign]

        await _run_chat(task)

        assert followups == [((str(task.id),), {"chat_only": True})]

    @pytest.mark.parametrize("status", [TaskStatus.DEFINED, TaskStatus.QUEUED])
    async def test_not_refining_skipped(
        self,
        db_session: AsyncSession,
        worker_env: WorkerEnv,
        followups: list[tuple[Any, ...]],
        status: TaskStatus,
    ) -> None:
        task = await _refining_task(db_session, status=status)

        await _run_chat(task)

        await db_session.refresh(task)
        assert (task.status, task.chat_active) == (status, False)
        assert worker_env.options == []

    async def test_owned_session_skipped(
        self,
        db_session: AsyncSession,
        worker_env: WorkerEnv,
        redis_client: Redis,
        monkeypatch: pytest.MonkeyPatch,
        followups: list[tuple[Any, ...]],
    ) -> None:
        task = await _refining_task(db_session)
        await _enqueue(db_session, task, "вопрос")
        monkeypatch.setattr(session_worker, "SESSION_OWNER_WAIT_SECONDS", 0.1)

        async with keep_session_heartbeat(redis_client, task.id, acquire_timeout=0):
            await _run_chat(task)

        await db_session.refresh(task)
        assert task.chat_active is False
        assert worker_env.options == []
        assert await _request_statuses(db_session, task) == [ManualRequestStatus.QUEUED]

    async def test_deferred_by_maintenance(
        self,
        db_session: AsyncSession,
        worker_env: WorkerEnv,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        task = await _refining_task(db_session)

        async def active(_redis: object) -> bool:
            return True

        monkeypatch.setattr(session_worker, "maintenance_active", active)

        await _run_chat(task)

        assert worker_env.enqueued == [
            (
                [str(task.id)],
                {"start_after_order_index": None, "continuation": False, "chat_only": True},
            ),
        ]


class TestSettleAfterError:
    @pytest.mark.parametrize(
        ("status", "expected"),
        [
            pytest.param(TaskStatus.AWAITING_INPUT, TaskStatus.REFINING, id="вопрос"),
            pytest.param(TaskStatus.PLAN_REVIEW, TaskStatus.REFINING, id="план"),
            pytest.param(TaskStatus.REFINING, TaskStatus.REFINING, id="ответ"),
            pytest.param(TaskStatus.DEFINED, TaskStatus.DEFINED, id="уже сменён"),
        ],
    )
    async def test_status(
        self,
        db_session: AsyncSession,
        status: TaskStatus,
        expected: TaskStatus,
    ) -> None:
        task = await _refining_task(db_session, status=status)
        task.chat_active = True
        await db_session.commit()

        await refining_chat.recover_lost_chat(db_session, task_id=task.id)

        await db_session.refresh(task)
        assert (task.status, task.chat_active) == (expected, False)


class TestPendingRequests:
    @pytest.mark.parametrize(
        ("status", "queued", "expected"),
        [
            pytest.param(TaskStatus.REFINING, True, True, id="ждёт"),
            pytest.param(TaskStatus.REFINING, False, False, id="пусто"),
            pytest.param(TaskStatus.DEFINED, True, False, id="ушла из уточнения"),
        ],
    )
    async def test_pending(
        self,
        db_session: AsyncSession,
        status: TaskStatus,
        queued: bool,
        expected: bool,
    ) -> None:
        task = await _refining_task(db_session)
        if queued:
            await _enqueue(db_session, task, "вопрос")
        task.status = status
        await db_session.commit()

        pending = await refining_chat.chat_has_pending_requests(db_session, task_id=task.id)
        assert pending is expected


class TestLostChat:
    @pytest.mark.parametrize(
        ("alive", "expected"),
        [
            pytest.param(True, (TaskStatus.AWAITING_INPUT, True), id="пульс есть"),
            pytest.param(False, (TaskStatus.REFINING, False), id="воркер погиб"),
        ],
    )
    async def test_bridge_check(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        alive: bool,
        expected: tuple[TaskStatus, bool],
    ) -> None:
        task = await _refining_task(db_session, status=TaskStatus.AWAITING_INPUT)
        await self._check(db_session, redis_client, task, alive=alive)
        assert (task.status, task.chat_active) == expected

    async def test_lost_during_answer(self, db_session: AsyncSession, redis_client: Redis) -> None:
        """Ответ агента без вопроса: задача в `refining`, а не в статусе сессии."""
        task = await _refining_task(db_session)
        await _enqueue(db_session, task, "вопрос")
        await db_session.execute(
            sa.update(TaskManualRequestQueue)
            .where(TaskManualRequestQueue.task_id == task.id)
            .values(status=ManualRequestStatus.PROCESSING),
        )

        await self._check(db_session, redis_client, task, alive=False)

        assert (task.status, task.chat_active) == (TaskStatus.REFINING, False)
        assert await _request_statuses(db_session, task) == [ManualRequestStatus.DONE]

    async def _check(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        task: Task,
        *,
        alive: bool,
    ) -> None:
        task.chat_active = True
        await db_session.commit()

        if alive:
            async with keep_session_heartbeat(redis_client, task.id, acquire_timeout=0):
                await check_session_bridges(db_session, redis_client=redis_client)
        else:
            await check_session_bridges(db_session, redis_client=redis_client)
        await db_session.refresh(task)


class TestChatBlocksBackgroundJobs:
    async def test_requests_not_expired(self, db_session: AsyncSession) -> None:
        task = await _refining_task(db_session)
        await _enqueue(db_session, task, "долгий ответ")
        task.chat_active = True
        await db_session.commit()

        expired = await expire_stale_manual_queue_requests(
            db_session,
            older_than=datetime.now(UTC) + timedelta(hours=1),
        )

        assert expired == []

    async def test_not_autostarted(self, db_session: AsyncSession) -> None:
        now = datetime.now(UTC)
        task = await _refining_task(db_session)
        task.chat_active = True
        task.auto_start_enabled = True
        task.scheduled_start_at = now - timedelta(minutes=1)
        await db_session.commit()

        found = await find_tasks_due_for_autostart(db_session, now=now)

        assert task.id not in {found_task.id for found_task in found}


class TestAdmission:
    """Скрипт из библиотеки LLM не нужен, но чат «Уточняется» ведёт только агент."""

    @pytest.mark.parametrize(
        ("status", "with_llm", "error"),
        [
            pytest.param(TaskStatus.REFINING, True, None, id="чат"),
            pytest.param(TaskStatus.REFINING, False, ValidationError, id="чат без LLM"),
            pytest.param(TaskStatus.IN_PROGRESS, False, None, id="скрипт в работе"),
            pytest.param(TaskStatus.DEFINED, True, ConflictError, id="не уточняется"),
        ],
    )
    def test_open(self, status: TaskStatus, with_llm: bool, error: type[Exception] | None) -> None:
        task = Task(status=status, llm_account_id=uuid.uuid4() if with_llm else None)
        task.manual_requests_closed = False

        if error is None:
            ensure_manual_requests_open(task)
        else:
            with pytest.raises(error):
                ensure_manual_requests_open(task)
