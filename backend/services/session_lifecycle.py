"""Решение "создать новую сессию или переиспользовать существующую" (раздел 6.1 ТЗ).

Чистая функция без побочных эффектов и без обращения к SDK/БД — решение,
которое оркестратор (этап 6) использует, чтобы собрать `ClaudeAgentOptions`
через `clients.claude_agent.build_claude_agent_options`.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SessionStartPlan:
    resume_session_id: str | None
    enable_remote_control: bool


def plan_session_start(*, existing_session_id: str | None) -> SessionStartPlan:
    """Раздел 6.1: сессия создаётся ровно один раз; повторный запуск переиспользует
    существующий `session_id`, если явно не выбрана очистка контекста (в этом случае
    вызывающий код обязан передать ``existing_session_id=None``, а не саму эту функцию —
    решение "очищать ли контекст" ей не принадлежит).

    Мост `/remote-control` (раздел 6.1, 6.3, решение №1 плана реализации) включается
    ТОЛЬКО при первом `connect()` задачи — то есть именно когда `session_id` ещё нет.
    """
    return SessionStartPlan(
        resume_session_id=existing_session_id,
        enable_remote_control=existing_session_id is None,
    )
