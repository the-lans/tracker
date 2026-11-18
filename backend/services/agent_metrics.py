"""Агрегирование диагностических показателей агентного хода."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

from app_logging.config import get_logger

DIAGNOSTICS_ENV = "CLAUDE_DIAGNOSTICS"
DIAGNOSTICS_MAX_TURNS_ENV = "CLAUDE_DIAGNOSTICS_MAX_TURNS"
TOOL_INPUT_LOG_LIMIT = 200
TOOL_LOG_EVENT_LIMIT = 50
DIAGNOSTIC_DISALLOWED_TOOLS = ["Agent", "Task", "Bash", "ListAgents"]
_SENSITIVE_TOOL_INPUT_KEYS = frozenset({"token", "secret", "password", "key"})
_SENSITIVE_TOOL_INPUT_PARTS = (
    "token",
    "secret",
    "password",
    "authorization",
    "credential",
    "cookie",
    "private_key",
)

# Сколько незавершённых инструментов перечислять в причине таймаута.
TIMEOUT_OPEN_TOOLS_LIMIT = 3

logger = get_logger("agent_metrics")


@dataclass
class TurnProgress:
    """
    Что успел ход к моменту таймаута: ответила ли модель (первое событие SDK
    приходит сразу, ещё до модели, поэтому считается только её ответ), сколько
    вызвано инструментов и какие из них не вернули результат. Только имена
    инструментов, без аргументов — текст попадает в `node_logs.error_message`.
    """

    model_responded: bool = False
    tool_call_count: int = 0
    open_tools: dict[str, str] = field(default_factory=dict)

    def tool_started(self, tool_use_id: str, name: str) -> None:
        self.tool_call_count += 1
        self.open_tools[tool_use_id] = name

    def tool_finished(self, tool_use_id: str) -> str | None:
        """Имя инструмента, вернувшего результат; None, если вызов не отслеживался."""
        return self.open_tools.pop(tool_use_id, None)

    def timeout_details(self) -> str:
        if not self.model_responded:
            return "ответ модели не начался"
        details = [f"инструментов: {self.tool_call_count}"]
        if self.open_tools:
            names = list(self.open_tools.values())[:TIMEOUT_OPEN_TOOLS_LIMIT]
            details.append(f"не завершены: {', '.join(names)}")
        return ", ".join(details)


def diagnostics_enabled() -> bool:
    return os.environ.get(DIAGNOSTICS_ENV, "").lower() in {"1", "true", "yes"}


def diagnostics_max_turns() -> int:
    value = os.environ.get(DIAGNOSTICS_MAX_TURNS_ENV)
    if not value:
        return 20
    try:
        turns = int(value)
    except ValueError:
        logger.warning("invalid_diagnostics_max_turns", value=value)
        return 20
    return turns if turns > 0 else 20


def tool_input_preview(value: object) -> str:
    """Возвращает короткие аргументы инструмента без известных секретов."""
    value = _redact_tool_input(value)
    try:
        serialized = json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        serialized = repr(value)
    return serialized[:TOOL_INPUT_LOG_LIMIT]


def _redact_tool_input(value: object) -> object:
    if isinstance(value, dict):
        return {
            key: "<redacted>" if _is_sensitive_key(key) else _redact_tool_input(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_tool_input(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact_tool_input(item) for item in value)
    return value


def _is_sensitive_key(key: object) -> bool:
    normalized = str(key).lower().replace("-", "_")
    return normalized in _SENSITIVE_TOOL_INPUT_KEYS or any(
        part in normalized for part in _SENSITIVE_TOOL_INPUT_PARTS
    )


def tool_result_preview(content: object) -> str:
    """Короткий текст результата инструмента для лога ошибки."""
    if isinstance(content, list):
        texts = [item.get("text", "") for item in content if isinstance(item, dict)]
        content = " ".join(str(text) for text in texts)
    return str(content or "")[:TOOL_INPUT_LOG_LIMIT]


def log_tool_finished(
    *,
    tool_name: str | None,
    duration_ms: int | None,
    is_error: bool,
    content: object,
) -> None:
    """
    Результат инструмента в диагностическом режиме: имя, длительность и для
    ошибки — начало её текста.
    """
    logger.info(
        "session_tool_finished",
        tool_name=tool_name,
        duration_ms=duration_ms,
        is_error=is_error,
        error=tool_result_preview(content) if is_error else None,
    )


def log_cli_stderr(line: str) -> None:
    logger.info("claude_cli_stderr", line=line[:TOOL_INPUT_LOG_LIMIT])
