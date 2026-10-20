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

Разрешение, зафиксированное пользователем (кнопкой или текстом в трекере,
раздел 9.6; `claude.ai/code` — только для просмотра, раздел 6.3), — это
API-эндпоинт, который АТОМАРНО заполняет `node_logs.user_input_text` данной
записи и публикует сигнал (`services.task_signal.publish_task_signal`).
Callback ниже ждёт именно этого: сигнал плюс непустой `user_input_text` на
нужной записи.

На время ожидания задача переходит в `plan_review`/`awaiting_input` (раздел
14.3: статус, WebSocket, push, подсветка на дашборде) и после решения
возвращается в статус, из которого ушла, — `in_progress` или `paused`.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny

from app_logging.config import get_logger
from db.models.enums import NodeLogStatus, PermissionMode, TaskStatus
from db.models.logs import NodeLog
from db.models.tasks import Task
from services.errors import ConflictError
from services.task_signal import wait_for_task_signal
from services.task_status import transition_task_status

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
    сообщить callback'у, какая запись `node_logs` сейчас "текущая".

    Заодно контекст знает, какая задача-обработчик SDK сейчас ждёт решения
    пользователя: SDK вызывает callback в своей задаче, и отмена хода
    воркером (таймаут ноды, «Остановить») эту задачу сама не отменяет.
    """

    node_log_id: uuid.UUID | None = None
    task_id: uuid.UUID | None = None
    auto_accept_plan: bool = False
    _decision_wait: asyncio.Task[Any] | None = field(default=None, init=False, repr=False)

    def activate(
        self,
        *,
        node_log_id: uuid.UUID,
        task_id: uuid.UUID,
        auto_accept_plan: bool = False,
    ) -> None:
        """
        Каждый, кто начинает ход в сессии (нода, ручной запрос, разрешение
        конфликта, пересказ), сообщает, к какой записи `node_logs` он относится.
        """
        self.node_log_id = node_log_id
        self.task_id = task_id
        self.auto_accept_plan = auto_accept_plan

    def track_decision_wait(self) -> None:
        self._decision_wait = asyncio.current_task()

    def untrack_decision_wait(self) -> None:
        if self._decision_wait is asyncio.current_task():
            self._decision_wait = None

    async def cancel_decision_wait(self) -> None:
        """
        Прерванный ход не должен оставлять задачу в ожидании решения.

        Отменяет ожидание и дожидается его `finally`, который возвращает
        статус задачи, — до того, как воркер решит, что делать с нодой дальше
        (повтор, `failed`).
        """
        waiting = self._decision_wait
        if waiting is None or waiting.done():
            return
        waiting.cancel()
        await asyncio.wait({waiting})
        logger.info("decision_wait_cancelled", node_log_id=str(self.node_log_id))


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


async def _wait_for_resolution(
    *,
    session_factory: Callable[[], AbstractAsyncContextManager[AsyncSession]],
    redis_client: Redis,
    task_id: uuid.UUID,
    node_log_id: uuid.UUID,
    timeout: float | None,
) -> str | None:
    """Ждёт записанного решения; `None` — истёк ``timeout``.

    Канал сигналов у задачи один на всё (раздел 7.3: постановка ручного
    запроса, команды управления тоже будят его) — сигнал сам по себе не
    означает решения, поэтому после каждого пробуждения решение
    перечитывается, а ожидание продолжается до дедлайна. Читать решение
    ДО первого сигнала нельзя: после «Доработать план» в записи остаётся
    прошлое решение, и следующий `ExitPlanMode` той же ноды принял бы его
    за новое.
    """
    loop = asyncio.get_running_loop()
    deadline = None if timeout is None else loop.time() + timeout
    while True:
        remaining = None if deadline is None else deadline - loop.time()
        if remaining is not None and remaining <= 0:
            return None
        if not await wait_for_task_signal(redis_client, task_id, timeout=remaining):
            return None
        async with session_factory() as db_session:
            resolution = await _read_resolution(db_session, node_log_id=node_log_id)
        if resolution is not None:
            return resolution
        logger.info("decision_wait_woken_without_resolution", node_log_id=str(node_log_id))


# Из этих статусов задача уходит в ожидание решения и в них же возвращается.
_DECISION_RESUMABLE_STATUSES = frozenset({TaskStatus.IN_PROGRESS, TaskStatus.PAUSED})


async def resumable_decision_status(
    db_session: AsyncSession,
    *,
    task_id: uuid.UUID,
) -> TaskStatus | None:
    """
    Статус, в который задачу вернуть после решения; `None` — статус на время
    ожидания не меняется.

    Так бывает, если задача в `rebase_conflict`: её конфликт разбирает
    воркер, а решение принимается и без смены статуса.
    """
    task = await db_session.get(Task, task_id, populate_existing=True)
    if task is None or task.status not in _DECISION_RESUMABLE_STATUSES:
        logger.info(
            "decision_status_not_changed",
            task_id=str(task_id),
            status=task.status if task is not None else None,
        )
        return None
    return task.status


async def enter_decision_status(
    db_session: AsyncSession,
    *,
    task_id: uuid.UUID,
    resume_status: TaskStatus,
    awaiting_status: TaskStatus,
) -> None:
    """Раздел 14.3: переход в `plan_review`/`awaiting_input` на время ожидания."""
    try:
        await transition_task_status(
            db_session,
            task_id=task_id,
            from_status=resume_status,
            to_status=awaiting_status,
        )
    except ConflictError:
        # Возврат после решения тогда не сработает по compare-and-swap —
        # статус остаётся тем, что выставил другой процесс.
        logger.info("decision_status_changed_concurrently", task_id=str(task_id))


async def leave_decision_status(
    db_session: AsyncSession,
    *,
    task_id: uuid.UUID,
    awaiting_status: TaskStatus,
    resume_status: TaskStatus,
) -> None:
    try:
        await transition_task_status(
            db_session,
            task_id=task_id,
            from_status=awaiting_status,
            to_status=resume_status,
        )
    except ConflictError:
        # Сбой сессии мог уже перевести задачу дальше (`fail_task_after_error`).
        logger.info("decision_status_left_concurrently", task_id=str(task_id))


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
    # Как и при решении пользователя: принятый план — успешная запись, по
    # ней `execute_plan_prompt_node` понимает, что план подтверждён.
    node_log.status = NodeLogStatus.SUCCESS
    node_log.finished_at = datetime.now(UTC)
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
    """
    Раздел 9.2, 9.6: единый callback на весь жизненный цикл сессии.

    Режим разрешений самой сессии переключает нода `plan_prompt`
    (`services/nodes/dispatch.py`); callback лишь записывает выбранный
    пользователем режим в `tasks.current_permission_mode`.
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

        awaiting_status = TaskStatus.PLAN_REVIEW if is_plan else TaskStatus.AWAITING_INPUT
        resume_status: TaskStatus | None = None
        # Регистрация — до первого изменения в БД: прерванный в любой момент
        # ход (`cancel_decision_wait`) проходит через `finally` ниже. Статус
        # возврата запоминается до перехода: отмена может прийти уже после
        # коммита перехода, а лишний возврат безопасен — это compare-and-swap.
        context.track_decision_wait()
        try:
            async with session_factory() as db_session:
                await _mark_awaiting_decision(
                    db_session,
                    node_log_id=context.node_log_id,
                    pending_question=question_text,
                    pending_plan_text=plan_text,
                    pending_options=options,
                )
                resume_status = await resumable_decision_status(
                    db_session,
                    task_id=context.task_id,
                )
                if resume_status is not None:
                    await enter_decision_status(
                        db_session,
                        task_id=context.task_id,
                        resume_status=resume_status,
                        awaiting_status=awaiting_status,
                    )
            logger.info(
                "awaiting_user_decision",
                node_log_id=str(context.node_log_id),
                tool_name=tool_name,
            )
            resolution = await _wait_for_resolution(
                session_factory=session_factory,
                redis_client=redis_client,
                task_id=context.task_id,
                node_log_id=context.node_log_id,
                timeout=decision_wait_timeout_seconds,
            )
        finally:
            # И после решения, и после таймаута, и при отмене хода (таймаут
            # ноды, «Остановить» — `cancel_decision_wait`) задача не должна
            # остаться в ожидании.
            context.untrack_decision_wait()
            if resume_status is not None:
                async with session_factory() as db_session:
                    await leave_decision_status(
                        db_session,
                        task_id=context.task_id,
                        awaiting_status=awaiting_status,
                        resume_status=resume_status,
                    )
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
