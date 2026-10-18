"""Режим планирования — раздел 9 ТЗ, включая универсальный виджет выбора (9.6).

Механизм разрешений Claude Agent SDK вызывает один и тот же callback перед
`ExitPlanMode` и `AskUserQuestion` (9.6) — обе ветки перехватываются здесь
единым кодом, а не двумя изолированными реализациями.

Мост между "текущей" нодой оркестратора и callback'ом, вызываемым SDK
асинхронно изнутри одной сессии на весь её жизненный цикл (`can_use_tool`
регистрируется один раз при `connect()`, раздел 6.1), — `ActiveNodeContext`:
оркестратор обязан выставлять его поля непосредственно перед `query()` и
не трогать их, пока не получен ответ (раздел 6.2 — сессия и так
последовательна, гонок между нодами нет).

Разрешение, зафиксированное пользователем (через любой из трёх каналов
раздела 9.6 — кнопку в трекере, текст в трекере, `claude.ai/code`), — это
API-эндпоинт (этап 12 плана), который АТОМАРНО заполняет
`node_logs.user_input_text` данной записи и публикует сигнал
(`services.task_signal.publish_task_signal`). Callback ниже ждёт именно
этого: сигнал плюс непустой `user_input_text` на нужной записи.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny

from app_logging.config import get_logger
from db.models.enums import NodeLogStatus, PermissionMode
from db.models.logs import NodeLog
from db.models.tasks import Task
from services.task_signal import wait_for_task_signal

if TYPE_CHECKING:
    from collections.abc import Callable
    from contextlib import AbstractAsyncContextManager

    from claude_agent_sdk.types import CanUseTool, ToolPermissionContext
    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger("plan_mode")

EXIT_PLAN_MODE_TOOL = "ExitPlanMode"
ASK_USER_QUESTION_TOOL = "AskUserQuestion"
INTERCEPTED_TOOLS = frozenset({EXIT_PLAN_MODE_TOOL, ASK_USER_QUESTION_TOOL})


class PlanDecisionOption:
    """Раздел 9.3: три варианта решения после завершения `plan_prompt` — идентификаторы
    `pending_options[].id`, которые API получает от пользователя обратно как решение.
    """

    ACCEPT_AUTO = "accept_auto"
    ACCEPT_DEFAULT = "accept_default"
    REVISE = "revise"


DEFAULT_PLAN_OPTIONS: list[dict[str, str]] = [
    {"id": PlanDecisionOption.ACCEPT_AUTO, "label": "Принять план и продолжить автоматически"},
    {
        "id": PlanDecisionOption.ACCEPT_DEFAULT,
        "label": "Принять план, подтверждать каждое действие",
    },
    {"id": PlanDecisionOption.REVISE, "label": "Доработать план"},
]


@dataclass(frozen=True, slots=True)
class PlanDecisionResult:
    allow: bool
    updated_permission_mode: PermissionMode | None = None
    feedback_text: str | None = None


def apply_plan_decision(option: str, *, feedback_text: str | None = None) -> PlanDecisionResult:
    """Раздел 9.3.

    ТЗ допускает `acceptEdits` ИЛИ `bypassPermissions` для варианта
    "продолжить автоматически", не выбирая между ними — реализация
    фиксирует менее опасный `acceptEdits` как дефолт.
    """
    if option == PlanDecisionOption.ACCEPT_AUTO:
        return PlanDecisionResult(allow=True, updated_permission_mode=PermissionMode.ACCEPT_EDITS)
    if option == PlanDecisionOption.ACCEPT_DEFAULT:
        return PlanDecisionResult(allow=True, updated_permission_mode=PermissionMode.DEFAULT)
    if option == PlanDecisionOption.REVISE:
        return PlanDecisionResult(allow=False, feedback_text=feedback_text)
    message = f"Неизвестный вариант решения по плану: {option}"
    raise ValueError(message)


def decide_plan_auto_completion(*, auto_accept_plan: bool) -> PlanDecisionResult | None:
    """Раздел 9.2: `auto_accept_plan=true` — подтверждение без остановки пайплайна.

    `None` означает "решение пользователя обязательно" (переход в `plan_review`).
    """
    if not auto_accept_plan:
        return None
    return PlanDecisionResult(allow=True, updated_permission_mode=PermissionMode.ACCEPT_EDITS)


@dataclass
class ActiveNodeContext:
    """Оркестратор выставляет перед каждым `query()` — единственный способ
    сообщить callback'у, какая запись `node_logs` сейчас "текущая"."""

    node_log_id: uuid.UUID | None = None
    task_id: uuid.UUID | None = None
    auto_accept_plan: bool = False


def _extract_question_options(tool_input: dict[str, Any]) -> list[dict[str, str]]:
    raw_options = tool_input.get("options") or tool_input.get("questions") or []
    options: list[dict[str, str]] = []
    for index, item in enumerate(raw_options):
        if isinstance(item, dict):
            options.append(
                {"id": str(item.get("id", index)), "label": str(item.get("label", item))},
            )
        else:
            options.append({"id": str(index), "label": str(item)})
    return options


async def _mark_awaiting_decision(
    db_session: AsyncSession,
    *,
    node_log_id: uuid.UUID,
    pending_question: str | None,
    pending_plan_text: str | None,
    pending_options: list[dict[str, str]],
) -> None:
    node_log = await db_session.get(NodeLog, node_log_id)
    if node_log is None:
        message = f"node_log {node_log_id} не найден"
        raise ValueError(message)
    node_log.status = NodeLogStatus.AWAITING_DECISION
    node_log.pending_question = pending_question
    node_log.pending_plan_text = pending_plan_text
    node_log.pending_options = pending_options
    await db_session.commit()


_DECISION_SEPARATOR = "\n"


def encode_decision(option_id: str, *, feedback_text: str | None = None) -> str:
    """Кодирует решение пользователя (раздел 9.6) в одно текстовое поле
    `node_logs.user_input_text` — API вызывает это перед записью.

    ``feedback_text`` обязателен по смыслу для "Доработать план" (раздел
    9.3), опционален для прочих вариантов; хранится второй строкой, чтобы
    не заводить под него отдельную колонку в уже зафиксированной схеме
    (раздел 3.1).
    """
    if feedback_text:
        return f"{option_id}{_DECISION_SEPARATOR}{feedback_text}"
    return option_id


def parse_decision(encoded: str) -> tuple[str, str | None]:
    option_id, separator, feedback_text = encoded.partition(_DECISION_SEPARATOR)
    return option_id, feedback_text if separator else None


async def _read_resolution(db_session: AsyncSession, *, node_log_id: uuid.UUID) -> str | None:
    """Возвращает закодированное решение (`encode_decision`), если оно уже
    записано (не `None`)."""
    node_log = await db_session.get(NodeLog, node_log_id)
    if node_log is None or node_log.user_input_text is None:
        return None
    return node_log.user_input_text


async def _record_plan_auto_accept(
    db_session: AsyncSession,
    *,
    node_log_id: uuid.UUID,
    task_id: uuid.UUID,
    plan_text: str | None,
) -> None:
    node_log = await db_session.get(NodeLog, node_log_id)
    if node_log is None:
        message = f"node_log {node_log_id} не найден"
        raise ValueError(message)
    node_log.pending_plan_text = plan_text
    node_log.user_input_text = PlanDecisionOption.ACCEPT_AUTO
    # Раздел 9.2: auto_accept_plan всегда продолжает в "auto"-режиме.
    await _set_task_permission_mode(db_session, task_id=task_id, mode=PermissionMode.ACCEPT_EDITS)
    await db_session.commit()


async def _set_task_permission_mode(
    db_session: AsyncSession,
    *,
    task_id: uuid.UUID,
    mode: PermissionMode,
) -> None:
    """Раздел 9.4: режим после утверждения плана — выбор пользователя, не
    фиксированное значение конфигурации ноды."""
    task = await db_session.get(Task, task_id)
    if task is not None:
        task.current_permission_mode = mode


def build_can_use_tool_callback(
    *,
    context: ActiveNodeContext,
    session_factory: Callable[[], AbstractAsyncContextManager[AsyncSession]],
    redis_client: Redis,
    decision_wait_timeout_seconds: float | None = None,
) -> CanUseTool:
    """Раздел 9.2, 9.6: единый callback на весь жизненный цикл сессии.

    Не входит в область этого модуля: диспетчер SDK-сообщений, который
    обнаруживает завершение планирования и переключает
    `tasks.current_permission_mode`/`ClaudeCodeSession.set_permission_mode`
    по результату (`PlanDecisionResult.updated_permission_mode`) — это
    оркестратор нод (`services/nodes/plan_prompt.py`), использующий этот
    callback лишь как один из компонентов.
    """

    async def can_use_tool(
        tool_name: str,
        tool_input: dict[str, Any],
        _permission_context: ToolPermissionContext,
    ) -> PermissionResultAllow | PermissionResultDeny:
        if tool_name not in INTERCEPTED_TOOLS:
            return PermissionResultAllow()
        if context.node_log_id is None or context.task_id is None:
            return PermissionResultDeny(message="Нет активной ноды для обработки решения")

        is_plan = tool_name == EXIT_PLAN_MODE_TOOL
        plan_text = tool_input.get("plan") if is_plan else None
        question_text = None if is_plan else str(tool_input.get("question", ""))
        options = DEFAULT_PLAN_OPTIONS if is_plan else _extract_question_options(tool_input)

        if is_plan and context.auto_accept_plan:
            async with session_factory() as db_session:
                await _record_plan_auto_accept(
                    db_session,
                    node_log_id=context.node_log_id,
                    task_id=context.task_id,
                    plan_text=plan_text,
                )
            logger.info("plan_auto_accepted", node_log_id=str(context.node_log_id))
            return PermissionResultAllow()

        async with session_factory() as db_session:
            await _mark_awaiting_decision(
                db_session,
                node_log_id=context.node_log_id,
                pending_question=question_text,
                pending_plan_text=plan_text,
                pending_options=options,
            )
        logger.info(
            "awaiting_user_decision",
            node_log_id=str(context.node_log_id),
            tool_name=tool_name,
        )

        received = await wait_for_task_signal(
            redis_client,
            context.task_id,
            timeout=decision_wait_timeout_seconds,
        )
        resolution: str | None = None
        if received:
            async with session_factory() as db_session:
                resolution = await _read_resolution(db_session, node_log_id=context.node_log_id)
        if resolution is None:
            return PermissionResultDeny(message="Истекло время ожидания решения пользователя")

        if not is_plan:
            return PermissionResultAllow(updated_input={**tool_input, "answer": resolution})

        option_id, feedback_text = parse_decision(resolution)
        decision = apply_plan_decision(option_id, feedback_text=feedback_text)
        async with session_factory() as db_session:
            node_log = await db_session.get(NodeLog, context.node_log_id)
            if node_log is not None:
                node_log.finished_at = datetime.now(UTC)
                node_log.status = NodeLogStatus.SUCCESS if decision.allow else NodeLogStatus.RUNNING
            if decision.allow and decision.updated_permission_mode is not None:
                await _set_task_permission_mode(
                    db_session,
                    task_id=context.task_id,
                    mode=decision.updated_permission_mode,
                )
            await db_session.commit()
        if decision.allow:
            return PermissionResultAllow()
        return PermissionResultDeny(message=decision.feedback_text or "", interrupt=False)

    return can_use_tool
