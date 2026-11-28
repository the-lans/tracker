"""Принятый план реализуется до следующей ноды и переживает прерывания."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
import sqlalchemy as sa
from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny

from clients.claude_agent import ClaudeCodeSession
from db.models.enums import NodeLogStatus, NodeLogTriggerType, NodeType, PermissionMode
from db.models.logs import NodeLog
from db.models.pipelines import Node
from services.limit_wait import _waiting_node_type
from services.llm_account_choice import LlmLimitWaitError
from services.node_history import accepted_plan_text
from services.nodes import dispatch
from services.nodes.dispatch import NodeExecutionOutcome
from services.pipeline_orchestrator import StopGuard, run_pipeline
from services.plan_execution import PLAN_COMPLETE, PLAN_IMPLEMENTING, implementation_prompt
from services.plan_mode import ActiveNodeContext, PlanDecisionOption, build_can_use_tool_callback
from services.task_control import TaskControlCommand, clear_task_control, request_task_control
from services.task_status import first_unfinished_order_index
from tests.fakes import FakeClaudeAgentClient, make_result_message, patch_plan_mode_signals
from tests.test_pipeline_orchestrator import _add_node, _make_task_with_pipeline, _node_logs_for
from tests.test_plan_mode import _TEST_TOOL_CONTEXT, _non_closing_session_factory, _question

if TYPE_CHECKING:
    from claude_agent_sdk.types import CanUseTool
    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncSession

    from db.models.tasks import Task


async def setup_plan(
    db: AsyncSession,
    redis: Redis,
) -> tuple[Task, ActiveNodeContext, CanUseTool]:
    task = await _make_task_with_pipeline(db)
    await _add_node(
        db,
        task,
        order_index=0,
        node_type=NodeType.PLAN_PROMPT,
        prompt_template="Plan then implement",
        max_retries=0,
    )
    await _add_node(
        db,
        task,
        order_index=1,
        node_type=NodeType.PLAIN_PROMPT,
        prompt_template="Review. Do not modify files.",
    )
    context = ActiveNodeContext()
    callback = build_can_use_tool_callback(
        context=context,
        session_factory=_non_closing_session_factory(db),
        redis_client=redis,
        decision_wait_timeout_seconds=5,
    )
    return task, context, callback


class TestPlanImplementation:
    @pytest.mark.parametrize(
        "option", [None, PlanDecisionOption.ACCEPT_AUTO, PlanDecisionOption.ACCEPT_DEFAULT]
    )
    async def test_implements_before_review(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        option: PlanDecisionOption | None,
    ) -> None:
        task, context, callback = await setup_plan(db_session, redis_client)
        task.auto_accept_plan = option is None
        marker = tmp_path / "implemented.txt"
        decisions = []

        async def answer(**_kwargs: object) -> bool:
            log = await db_session.get(NodeLog, context.node_log_id)
            assert log is not None
            if log.pending_plan_text is not None:
                decisions.append(log.pending_plan_text)
                log.user_input_text = option
            else:
                assert log.pending_options
                log.user_input_text = str(log.pending_options[0]["id"])
            await db_session.commit()
            return True

        patch_plan_mode_signals(monkeypatch, answer)

        async def turn() -> None:
            if context.plan_mode:
                result = await callback(
                    "ExitPlanMode", {"plan": "Add validation"}, _TEST_TOOL_CONTEXT
                )
                assert isinstance(result, PermissionResultDeny) and result.interrupt
            elif len(fake.queries) == 2:
                log = await db_session.get(NodeLog, context.node_log_id)
                assert log is not None and log.status is NodeLogStatus.RUNNING
                assert log.finished_at is None
                assert log.plan_execution is not None
                assert log.plan_execution["phase"] == PLAN_IMPLEMENTING
                assert await first_unfinished_order_index(db_session, task.id) == 0
                assert await accepted_plan_text(db_session, task.id) == "Add validation"
                assert not context.plan_accepted
                assert isinstance(
                    await callback("Write", {}, _TEST_TOOL_CONTEXT),
                    PermissionResultAllow,
                )
                question = {"questions": [_question("Какую проверку?", "Unit", "Integration")]}
                assert isinstance(
                    await callback("AskUserQuestion", question, _TEST_TOOL_CONTEXT),
                    PermissionResultAllow,
                )
                assert await accepted_plan_text(db_session, task.id) == "Add validation"
                marker.write_text("done")
            else:
                assert marker.read_text() == "done"

        fake = FakeClaudeAgentClient(
            messages_per_query=[
                [make_result_message(is_error=True, terminal_reason="aborted_tools")],
                [make_result_message()],
                [make_result_message()],
            ],
            on_query=turn,
        )
        outcome = await run_pipeline(
            db_session,
            task=task,
            claude_session=ClaudeCodeSession(fake),
            repos_path=tmp_path,
            active_node_context=context,
        )
        assert outcome.completed
        assert fake.queries == [
            "Plan then implement",
            implementation_prompt("Add validation"),
            "Review. Do not modify files.",
        ]
        assert decisions == ([] if option is None else ["Add validation"])
        assert fake.permission_modes == [
            "plan",
            "default" if option == PlanDecisionOption.ACCEPT_DEFAULT else "acceptEdits",
        ]
        logs = await _node_logs_for(db_session, task.id)
        assert logs[0].status is NodeLogStatus.SUCCESS
        assert logs[0].plan_execution is not None
        assert logs[0].plan_execution["phase"] == PLAN_COMPLETE

    @pytest.mark.parametrize("stop", [False, True])
    async def test_resumes_implementation_without_replanning(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        tmp_path: Path,
        stop: bool,
    ) -> None:
        task, context, callback = await setup_plan(db_session, redis_client)
        task.auto_accept_plan = True
        gate_types: list[NodeType | None] = []

        async def gate(*, node_type: NodeType | None = None) -> None:
            gate_types.append(node_type)

        async def first_turn() -> None:
            if context.plan_mode:
                await callback("ExitPlanMode", {"plan": "Keep partial work"}, _TEST_TOOL_CONTEXT)
            else:
                (tmp_path / "partial.txt").write_text("preserve")
                if stop:
                    await request_task_control(redis_client, task.id, TaskControlCommand.STOP)
                    await asyncio.Future()

        fake = FakeClaudeAgentClient(
            messages_per_query=[
                [make_result_message(is_error=True, terminal_reason="aborted_tools")],
                [make_result_message(is_error=True)],
            ],
            on_query=first_turn,
        )
        outcome = await run_pipeline(
            db_session,
            task=task,
            claude_session=ClaudeCodeSession(fake),
            repos_path=tmp_path,
            active_node_context=context,
            limit_gate=gate,
            stop_guard=StopGuard(redis_client=redis_client, task_id=task.id),
        )
        assert not outcome.completed
        assert outcome.failed_order_index == 0
        assert outcome.stopped is stop
        assert await first_unfinished_order_index(db_session, task.id) == 0
        assert await accepted_plan_text(db_session, task.id) == "Keep partial work"
        await clear_task_control(redis_client, task.id)
        log = (await _node_logs_for(db_session, task.id))[0]
        assert log.status is (NodeLogStatus.STOPPED if stop else NodeLogStatus.FAILED)

        async def resume_turn() -> None:
            assert not context.plan_mode
            assert (tmp_path / "partial.txt").read_text() == "preserve"

        resumed = FakeClaudeAgentClient(
            messages_per_query=[[make_result_message()], [make_result_message()]],
            on_query=resume_turn,
        )
        result = await run_pipeline(
            db_session,
            task=task,
            claude_session=ClaudeCodeSession(resumed),
            repos_path=tmp_path,
            active_node_context=context,
            limit_gate=gate,
        )
        assert result.completed
        assert resumed.queries == [
            implementation_prompt("Keep partial work"),
            "Review. Do not modify files.",
        ]

        assert gate_types == [NodeType.PLAN_PROMPT, NodeType.PLAIN_PROMPT, NodeType.PLAIN_PROMPT]

    @pytest.mark.parametrize("stale", [False, True])
    @pytest.mark.parametrize("notice", [None, "Пользователь ответил: использовать PostgreSQL"])
    async def test_recovers_accepted_plan_after_worker_loss(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        tmp_path: Path,
        stale: bool,
        notice: str | None,
    ) -> None:
        task, context, _callback = await setup_plan(db_session, redis_client)
        node_id = await db_session.scalar(
            sa.select(Node.id).where(Node.pipeline_id == task.pipeline_id, Node.order_index == 0)
        )
        state = {
            "phase": PLAN_IMPLEMENTING,
            "plan": "Saved plan",
            "permission_mode": "default",
        }
        log = NodeLog(
            task_id=task.id,
            node_id=node_id,
            trigger_type=NodeLogTriggerType.PIPELINE,
            status=NodeLogStatus.RUNNING,
            decision_checkpoint={"recovery_notice": notice} if notice else None,
            plan_execution={"phase": "planning"} if stale else state,
        )
        db_session.add(log)
        await db_session.flush()
        if stale:
            # Callback обновил БД в отдельной сессии, текущая ORM-карта устарела.
            await db_session.execute(
                sa.update(NodeLog)
                .where(NodeLog.id == log.id)
                .values(plan_execution=state)
                .execution_options(synchronize_session=False),
            )
        task.current_permission_mode = PermissionMode.DEFAULT
        await db_session.commit()
        fake = FakeClaudeAgentClient(
            messages_per_query=[[make_result_message()], [make_result_message()]]
        )
        result = await run_pipeline(
            db_session,
            task=task,
            claude_session=ClaudeCodeSession(fake),
            repos_path=tmp_path,
            active_node_context=context,
        )
        assert result.completed
        assert fake.queries == [
            implementation_prompt("Saved plan", recovery_notice=notice),
            "Review. Do not modify files.",
        ]
        assert fake.permission_modes == ["default"]

    async def test_waits_for_limit_without_losing_plan(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        task, context, callback = await setup_plan(db_session, redis_client)
        task.auto_accept_plan = True
        until = datetime.now(UTC) + timedelta(minutes=10)
        original = dispatch.execute_llm_node_with_timeout
        calls = 0

        async def execute(
            session: ClaudeCodeSession,
            prompt: str,
            **kwargs: Any,
        ) -> NodeExecutionOutcome:
            nonlocal calls
            calls += 1
            if calls == 2:
                return NodeExecutionOutcome(success=False, limit_wait_until=until)
            return await original(session, prompt, **kwargs)

        monkeypatch.setattr(dispatch, "execute_llm_node_with_timeout", execute)

        async def accept() -> None:
            await callback("ExitPlanMode", {"plan": "Keep accepted plan"}, _TEST_TOOL_CONTEXT)

        fake = FakeClaudeAgentClient(
            messages_per_query=[
                [make_result_message(is_error=True, terminal_reason="aborted_tools")]
            ],
            on_query=accept,
        )
        with pytest.raises(LlmLimitWaitError) as exc:
            await run_pipeline(
                db_session,
                task=task,
                claude_session=ClaudeCodeSession(fake),
                repos_path=tmp_path,
                active_node_context=context,
            )
        assert exc.value.until == until
        assert fake.queries == ["Plan then implement"]
        assert await first_unfinished_order_index(db_session, task.id) == 0
        assert await accepted_plan_text(db_session, task.id) == "Keep accepted plan"
        task.limit_wait_order_index = 0
        await db_session.flush()
        assert await _waiting_node_type(db_session, task) is NodeType.PLAIN_PROMPT
        monkeypatch.setattr(dispatch, "execute_llm_node_with_timeout", original)
        resumed = FakeClaudeAgentClient(
            messages_per_query=[[make_result_message()], [make_result_message()]]
        )
        result = await run_pipeline(
            db_session,
            task=task,
            claude_session=ClaudeCodeSession(resumed),
            repos_path=tmp_path,
            active_node_context=context,
        )
        assert result.completed
        assert resumed.queries[0] == implementation_prompt("Keep accepted plan")
