"""`services/failure_classification.py` — временные и постоянные сбои SDK (раздел 17.3)."""

from __future__ import annotations

import pytest
from claude_agent_sdk import (
    ClaudeSDKError,
    CLIConnectionError,
    CLIJSONDecodeError,
    CLINotFoundError,
    ProcessError,
)

from services.failure_classification import (
    is_transient_assistant_error,
    is_transient_sdk_exception,
)


class TestAssistantErrors:
    @pytest.mark.parametrize(
        ("assistant_error", "transient"),
        [
            ("authentication_failed", False),
            ("billing_error", False),
            ("invalid_request", False),
            ("rate_limit", True),
            ("server_error", True),
            ("unknown", True),
            (None, True),
        ],
    )
    def test_classifies(self, assistant_error: str | None, transient: bool) -> None:
        assert is_transient_assistant_error(assistant_error) is transient


class TestSdkExceptions:
    @pytest.mark.parametrize(
        ("exc", "transient"),
        [
            (CLINotFoundError("claude не найден"), False),
            (ProcessError("процесс упал", exit_code=1), True),
            (CLIConnectionError("соединение оборвано"), True),
            (CLIJSONDecodeError("{", ValueError("bad")), True),
            (ClaudeSDKError("прочее"), True),
        ],
        ids=["not_found", "process", "connection", "json", "generic"],
    )
    def test_classifies(self, exc: ClaudeSDKError, transient: bool) -> None:
        assert is_transient_sdk_exception(exc) is transient
