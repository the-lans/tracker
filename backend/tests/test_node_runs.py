"""Тесты `services/node_runs.py`: итог выполнения в записи `node_logs`."""

from __future__ import annotations

import uuid

import pytest

from db.models.enums import NodeLogStatus, NodeLogTriggerType
from db.models.logs import NodeLog
from services.node_runs import apply_node_outcome
from services.nodes.dispatch import NodeExecutionOutcome

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
