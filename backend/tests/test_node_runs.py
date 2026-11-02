"""Тесты `services/node_runs.py`: итог выполнения в записи `node_logs`."""

from __future__ import annotations

import uuid

import pytest

from clients.claude_agent import ClaudeCodeSession
from db.models.enums import NodeLogStatus, NodeLogTriggerType, NodeType, ReasoningEffort
from db.models.logs import NodeLog
from services.llm_routing import TurnRoute
from services.node_runs import apply_node_outcome, mark_node_log_stopped
from services.nodes.dispatch import NodeExecutionOutcome
from tests.fakes import FakeClaudeAgentClient

_TIMEOUT = "Превышен таймаут выполнения"


class TestApplyNodeOutcome:
    """Раздел 15.2: лента показывает, почему выполнение не удалось."""

    @pytest.mark.parametrize(
        ("outcome", "success", "status", "error_message"),
        [
            (NodeExecutionOutcome(success=True, llm_output_text="готово"), None, "success", None),
            (
                NodeExecutionOutcome(success=False, llm_output_text="а", error_message=_TIMEOUT),
                None,
                "failed",
                _TIMEOUT,
            ),
            # Конфликт ребейза не разобран, хотя ход агента прошёл.
            (NodeExecutionOutcome(success=True, llm_output_text="ok"), False, "failed", None),
        ],
    )
    def test_error_message(
        self,
        outcome: NodeExecutionOutcome,
        success: bool | None,
        status: str,
        error_message: str | None,
    ) -> None:
        node_log = NodeLog(
            task_id=uuid.uuid4(),
            trigger_type=NodeLogTriggerType.LIBRARY_MANUAL,
            error_message="прошлая попытка",
        )

        apply_node_outcome(node_log, outcome, success=success)

        assert node_log.status is NodeLogStatus(status)
        assert node_log.error_message == error_message
        assert node_log.llm_output_text == outcome.llm_output_text


_ROUTE = TurnRoute(
    account_id=uuid.uuid4(),
    prefix="acc-0123456789ab",
    model="gpt-6-sol",
    effort=ReasoningEffort.MAX,
    provider_effort=ReasoningEffort.XHIGH,
)


def _node_log() -> NodeLog:
    return NodeLog(task_id=uuid.uuid4(), trigger_type=NodeLogTriggerType.PIPELINE)


class TestTurnRoute:
    """Раздел 19.7: `node_logs` фиксирует аккаунт, модель и уровень, ушедший провайдеру."""

    @pytest.mark.parametrize("success", [True, False])
    def test_recorded_with_outcome(self, success: bool) -> None:
        node_log = _node_log()

        apply_node_outcome(node_log, NodeExecutionOutcome(success=success, route=_ROUTE))

        assert (node_log.llm_account_id, node_log.llm_model, node_log.reasoning_effort) == (
            _ROUTE.account_id,
            "gpt-6-sol",
            ReasoningEffort.XHIGH,
        )

    def test_script_without_route(self) -> None:
        node_log = _node_log()

        apply_node_outcome(node_log, NodeExecutionOutcome(success=True, script_exit_code=0))

        assert (node_log.llm_account_id, node_log.llm_model, node_log.reasoning_effort) == (
            None,
            None,
            None,
        )

    @pytest.mark.parametrize(
        ("node_type", "recorded"),
        [(NodeType.PLAIN_PROMPT, True), (NodeType.SCRIPT, False)],
    )
    def test_stopped_turn_keeps_route(self, node_type: NodeType, recorded: bool) -> None:
        session = ClaudeCodeSession(FakeClaudeAgentClient(messages_per_query=[]))
        session.turn_route = _ROUTE
        node_log = _node_log()

        mark_node_log_stopped(node_log, node_type=node_type, claude_session=session)

        assert node_log.llm_account_id == (_ROUTE.account_id if recorded else None)
