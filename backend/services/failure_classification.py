"""
Временные и постоянные сбои Claude Agent SDK (раздел 17.3 ТЗ).

Временный сбой стоит повторить по retry-политике ноды (раздел 11.7);
постоянный повтором не лечится — нода сразу падает, задача уходит в
`failed`, автор получает уведомление. Сбои GitLab API классифицирует сам
клиент (`clients/gitlab.py`, `ExternalServiceError.is_transient`).
"""

from __future__ import annotations

from claude_agent_sdk import ClaudeSDKError, CLINotFoundError

# `AssistantMessage.error` (claude_agent_sdk.types.AssistantMessageError):
# неверный логин, неоплаченный аккаунт и отклонённый запрос не исправятся
# повтором; `rate_limit`, `server_error` и `unknown` — временные.
PERMANENT_ASSISTANT_ERRORS = frozenset(
    {"authentication_failed", "billing_error", "invalid_request"},
)


def is_transient_assistant_error(assistant_error: str | None) -> bool:
    return assistant_error not in PERMANENT_ASSISTANT_ERRORS


def is_transient_sdk_exception(exc: ClaudeSDKError) -> bool:
    """
    Не найденный CLI — ошибка установки, повтор бесполезен. Остальные
    исключения SDK (упавший процесс CLI, обрыв соединения, ошибка разбора
    потока) — временные: после переподключения сессии ход можно повторить.
    """
    return not isinstance(exc, CLINotFoundError)
