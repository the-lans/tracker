"""Режим планирования — раздел 9 ТЗ, включая универсальный виджет выбора (9.6).

Механизм разрешений Claude Agent SDK вызывает один и тот же callback перед
любым проверяемым инструментом — `ExitPlanMode`, `AskUserQuestion` и
действиями, которые режим разрешений сессии не одобряет сам. Все случаи,
где нужен ответ пользователя, проходят через один виджет выбора (9.6):

- `ExitPlanMode` — решение по плану (9.3); принятый план завершает ход ноды
  `plan_prompt` без изменений (до конца хода инструменты запрещены), режим
  сессии на выбранный пользователем переключает `execute_plan_prompt_node`
  после хода — реализация выполняется отдельным ходом той же ноды;
- `AskUserQuestion` — вопросы агента в формате SDK (`questions[]`), задаются
  по очереди, ответы возвращаются в `answers` (вопрос → выбранный вариант
  или свой текст);
- прочие инструменты: на этапе планирования изменения запрещены
  (9.1); в режиме `default` («подтверждать каждое действие») действие ждёт
  «Разрешить»/«Запретить»; иначе задача работает автономно (3.1).

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
import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import sqlalchemy as sa
from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny

from app_logging.config import get_logger
from db.models.enums import NodeLogStatus, PermissionMode, TaskStatus
from db.models.enums import PlanDecisionOption as PlanDecisionOption
from db.models.logs import DECISION_CHECKPOINT_ID, NodeLog
from db.models.mixins import JsonValue
from db.models.tasks import Task
from prompts.agent import (
    CONTEXT_ONLY_TOOL_DENIED,
    DECISION_TIMEOUT_DENIED,
    EMPTY_PLAN_DENIED,
    NO_ACTIVE_NODE_DENIED,
    NO_QUESTIONS_DENIED,
    PLAN_ACCEPTED_MESSAGE,
    PLAN_ACCEPTED_TOOL_DENIED,
    PLAN_MODE_WRITE_DENIED,
    PLAN_REVISE_DENIED,
    PLANNING_NOT_ACTIVE_DENIED,
    TOOL_DENIED_BY_USER,
)
from services.access import get_task_record_or_404
from services.errors import ConflictError, ValidationError
from services.plan_execution import accept_plan_execution
from services.session_heartbeat import require_session_owner
from services.task_signal import (
    TaskSignalSubscription,
    publish_task_signal,
    subscribe_task_signal,
)
from services.task_status import plan_accepted_in_run, transition_task_status

if TYPE_CHECKING:
    from collections.abc import Callable
    from contextlib import AbstractAsyncContextManager

    from claude_agent_sdk.types import CanUseTool, ToolPermissionContext
    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncSession

    from clients.claude_agent import UserWaitClock

logger = get_logger("plan_mode")

EXIT_PLAN_MODE_TOOL = "ExitPlanMode"
ENTER_PLAN_MODE_TOOL = "EnterPlanMode"
ASK_USER_QUESTION_TOOL = "AskUserQuestion"
INTERCEPTED_TOOLS = frozenset({EXIT_PLAN_MODE_TOOL, ASK_USER_QUESTION_TOOL})

# Ответ на вопрос агента своим текстом (SDK сам добавляет вариант «Другое»).
CUSTOM_ANSWER_OPTION = "custom"
PREVIOUS_QUESTION_OPTION = "previous_question"
TOOL_APPROVAL_ALLOW = "allow"
TOOL_APPROVAL_DENY = "deny"
TOOL_APPROVAL_OPTIONS: list[dict[str, str]] = [
    {"id": TOOL_APPROVAL_ALLOW, "label": "Разрешить"},
    {"id": TOOL_APPROVAL_DENY, "label": "Запретить"},
]
_TOOL_DESCRIPTION_LIMIT = 500


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


def plan_revise_message(feedback_text: str | None) -> str:
    """Раздел 9.3: фидбек «Доработать план» — с пожеланиями пользователя, если они есть."""
    if not feedback_text or not feedback_text.strip():
        return PLAN_REVISE_DENIED
    return f"{PLAN_REVISE_DENIED}: {feedback_text.strip()}"


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
    manual_request_id: uuid.UUID | None = None
    # Идёт нода `plan_prompt` и план ещё не принят: изменения запрещены (9.1).
    plan_mode: bool = False
    # План принят, ход ноды `plan_prompt` дописывается: инструменты запрещены (9.3).
    plan_accepted: bool = False
    # Ход лишь передаёт контекст (саммари родителя, 6.7): инструменты запрещены.
    context_only: bool = False
    # Длина ответа текущего хода (`ClaudeCodeSession.turn_text_length`):
    # место решения пользователя в ответе (раздел 15.2).
    output_length: Callable[[], int] | None = None
    # Часы ожидания пользователя сессии: на это время таймаут ноды стоит (7.3).
    user_wait_clock: UserWaitClock | None = None
    _decision_wait: asyncio.Task[Any] | None = field(default=None, init=False, repr=False)

    def activate(
        self,
        *,
        node_log_id: uuid.UUID,
        task_id: uuid.UUID,
        manual_request_id: uuid.UUID | None = None,
        plan_mode: bool = False,
        context_only: bool = False,
    ) -> None:
        """
        Каждый, кто начинает ход в сессии (нода, ручной запрос, разрешение
        конфликта, пересказ), сообщает, к какой записи `node_logs` он относится.
        """
        self.node_log_id = node_log_id
        self.task_id = task_id
        self.manual_request_id = manual_request_id
        self.plan_mode = plan_mode
        self.plan_accepted = False
        self.context_only = context_only

    def output_offset(self) -> int | None:
        return self.output_length() if self.output_length is not None else None

    def track_decision_wait(self) -> None:
        self._decision_wait = asyncio.current_task()
        if self.user_wait_clock is not None:
            self.user_wait_clock.begin()

    def untrack_decision_wait(self) -> None:
        if self._decision_wait is asyncio.current_task():
            self._decision_wait = None
            if self.user_wait_clock is not None:
                self.user_wait_clock.end()

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


async def _get_node_log(db_session: AsyncSession, node_log_id: uuid.UUID) -> NodeLog:
    """
    Запись активной ноды: её отсутствие — ошибка реализации, а не сценарий.
    """
    node_log = await db_session.get(NodeLog, node_log_id)
    if node_log is None:
        message = f"node_log {node_log_id} не найден"
        raise ValueError(message)
    return node_log


def _decision_checkpoint(
    *,
    resume_status: TaskStatus | None,
    awaiting_status: TaskStatus,
    manual_request_id: uuid.UUID | None,
    questionnaire: JsonValue | None,
) -> JsonValue:
    return {
        DECISION_CHECKPOINT_ID: str(uuid.uuid4()),
        "resume_status": resume_status.value if resume_status is not None else None,
        "awaiting_status": awaiting_status.value,
        "manual_request_id": str(manual_request_id) if manual_request_id is not None else None,
        "questionnaire": questionnaire,
    }


async def _mark_awaiting_decision(
    db_session: AsyncSession,
    *,
    node_log_id: uuid.UUID,
    pending_question: str | None,
    pending_plan_text: str | None,
    pending_options: list[dict[str, str]],
    output_offset: int | None,
    checkpoint: JsonValue,
) -> None:
    node_log = await _get_node_log(db_session, node_log_id)
    node_log.status = NodeLogStatus.AWAITING_DECISION
    node_log.decision_output_offset = output_offset
    node_log.decision_checkpoint = checkpoint
    node_log.pending_question = pending_question
    node_log.pending_plan_text = pending_plan_text
    node_log.pending_options = pending_options
    # Прошлое решение той же записи (предыдущий вопрос, «Доработать план») не
    # должно сойти за ответ на новый вопрос.
    node_log.user_input_text = None
    await db_session.commit()


_DECISION_SEPARATOR = "\n"


def encode_decision(option_id: str, *, feedback_text: str | None = None) -> str:
    """Кодирует решение пользователя (раздел 9.6) в одно текстовое поле
    `node_logs.user_input_text` — API вызывает это перед записью.

    ``feedback_text`` — пожелания к доработке плана или комментарий к
    решению (раздел 9.3), всегда необязателен; хранится второй строкой, чтобы
    не заводить под него отдельную колонку в уже зафиксированной схеме
    (раздел 3.1).
    """
    if feedback_text:
        return f"{option_id}{_DECISION_SEPARATOR}{feedback_text}"
    return option_id


def parse_decision(encoded: str) -> tuple[str, str | None]:
    option_id, separator, feedback_text = encoded.partition(_DECISION_SEPARATOR)
    return option_id, feedback_text if separator else None


async def record_user_decision(
    db_session: AsyncSession,
    *,
    task: Task,
    node_log_id: uuid.UUID,
    option_id: str,
    feedback_text: str | None,
    redis_client: Redis,
    decision_id: uuid.UUID | None = None,
) -> None:
    """
    Раздел 9.6: решение по плану, ответ на вопрос агента и подтверждение
    действия приходят одним путём — решение записывается в
    `node_logs.user_input_text` ожидающей записи, ожидающий callback
    будится сигналом задачи.
    """
    node_log = await get_task_record_or_404(
        db_session,
        NodeLog,
        node_log_id,
        task_id=task.id,
        not_found=f"Запись node_logs {node_log_id} не найдена у этой задачи",
    )
    if node_log.status is not NodeLogStatus.AWAITING_DECISION:
        raise ValidationError("Эта запись не ожидает решения")
    current_id = node_log.pending_decision_id
    submitted_id = str(decision_id) if decision_id is not None else None
    if submitted_id != current_id:
        raise ConflictError("Вопрос уже изменился")
    resolution = encode_decision(option_id, feedback_text=feedback_text)
    saved = await db_session.scalar(
        sa.update(NodeLog)
        .where(
            NodeLog.id == node_log_id,
            NodeLog.status == NodeLogStatus.AWAITING_DECISION,
            NodeLog.user_input_text.is_(None),
            NodeLog.decision_checkpoint[DECISION_CHECKPOINT_ID]
            .as_string()
            .is_not_distinct_from(current_id),
        )
        .values(user_input_text=resolution)
        .returning(NodeLog.id)
    )
    if saved is None:
        await db_session.refresh(node_log)
        if node_log.status is not NodeLogStatus.AWAITING_DECISION:
            raise ValidationError("Эта запись не ожидает решения")
        if node_log.pending_decision_id != current_id or node_log.user_input_text != resolution:
            raise ConflictError("Ответ на этот запрос уже сохранён")
    await db_session.commit()
    await publish_task_signal(redis_client, task.id)


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
    signals: TaskSignalSubscription,
    node_log_id: uuid.UUID,
    timeout: float | None,
) -> str | None:
    """Ждёт записанного решения; `None` — истёк ``timeout``.

    Канал сигналов у задачи один на всё (раздел 7.3: постановка ручного
    запроса, команды управления тоже будят его) — сигнал сам по себе не
    означает решения, поэтому решение перечитывается перед каждым ожиданием.
    Подписка открыта до того, как запись стала ожидать решения, а прошлое
    решение запись уже сбросила (`_mark_awaiting_decision`): ответ,
    пришедший раньше ожидания, не теряется и не путается с прежним.
    """
    loop = asyncio.get_running_loop()
    deadline = None if timeout is None else loop.time() + timeout
    while True:
        async with session_factory() as db_session:
            resolution = await _read_resolution(db_session, node_log_id=node_log_id)
        if resolution is not None:
            return resolution
        remaining = None if deadline is None else deadline - loop.time()
        if remaining is not None and remaining <= 0:
            return None
        if not await signals.wait(timeout=remaining):
            return None
        logger.info("decision_wait_woken", node_log_id=str(node_log_id))


# Из этих статусов задача уходит в ожидание решения и в них же возвращается;
# `refining` — чат с агентом до запуска (раздел 14.4).
_DECISION_RESUMABLE_STATUSES = frozenset(
    {TaskStatus.IN_PROGRESS, TaskStatus.PAUSED, TaskStatus.REFINING},
)


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
            db_session=db_session,
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
            db_session=db_session,
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
    output_offset: int | None,
) -> None:
    node_log = await _get_node_log(db_session, node_log_id)
    node_log.pending_plan_text = plan_text
    node_log.decision_output_offset = output_offset
    node_log.user_input_text = PlanDecisionOption.ACCEPT_AUTO
    # Самостоятельный ручной ход завершается; нода плана остаётся running
    # с сохранённым принятием до результата реализации.
    node_log.status = NodeLogStatus.SUCCESS
    node_log.finished_at = datetime.now(UTC)
    accept_plan_execution(node_log, mode=PermissionMode.ACCEPT_EDITS)
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


def _option_label(options: list[dict[str, str]], option_id: str) -> str | None:
    return next((option["label"] for option in options if option["id"] == option_id), None)


def answer_from_resolution(resolution: str, options: list[dict[str, str]]) -> str:
    """Ответ на вопрос агента: выбранный вариант (с комментарием) или свой текст."""
    option_id, feedback_text = parse_decision(resolution)
    label = _option_label(options, option_id)
    if label is None:
        return feedback_text or option_id
    return f"{label}. {feedback_text}" if feedback_text else label


def _question_options(question: dict[str, Any]) -> list[dict[str, str]]:
    raw_options = question.get("options") or []
    return [
        {"id": str(index), "label": str(option.get("label", ""))}
        for index, option in enumerate(raw_options)
        if isinstance(option, dict)
    ]


def describe_tool_call(tool_name: str, tool_input: dict[str, Any]) -> str:
    """Что агент хочет сделать — текст вопроса «Разрешить/Запретить»."""
    detail = tool_input.get("command") or tool_input.get("file_path")
    if not isinstance(detail, str):
        detail = json.dumps(tool_input, ensure_ascii=False)
    return f"Агент хочет выполнить {tool_name}: {detail[:_TOOL_DESCRIPTION_LIMIT]}"


async def _task_permission_mode(
    db_session: AsyncSession,
    *,
    task_id: uuid.UUID,
) -> PermissionMode | None:
    task = await db_session.get(Task, task_id, populate_existing=True)
    return task.current_permission_mode if task is not None else None


async def advance_recovered_question(
    db_session: AsyncSession, log: NodeLog, resolution: str
) -> str | None:
    """Сохраняет следующий вопрос или возвращает ответы завершённой серии."""
    assert log.decision_checkpoint is not None
    checkpoint = dict(log.decision_checkpoint)
    state = checkpoint["questionnaire"]
    questions = state["questions"]
    index = state["index"]
    answers = dict(state["answers"])
    if index and resolution == PREVIOUS_QUESTION_OPTION:
        index -= 1
    else:
        question = questions[index]
        answers[str(question.get("question", ""))] = answer_from_resolution(
            resolution, _question_options(question)
        )
        index += 1
    if index == len(questions):
        return "\n".join(f"{question}: {answer}" for question, answer in answers.items())
    question = questions[index]
    options = _question_options(question)
    if index:
        options.append({"id": PREVIOUS_QUESTION_OPTION, "label": "Назад"})
    checkpoint[DECISION_CHECKPOINT_ID] = str(uuid.uuid4())
    checkpoint["questionnaire"] = {"questions": questions, "index": index, "answers": answers}
    await _mark_awaiting_decision(
        db_session,
        node_log_id=log.id,
        pending_question=str(question.get("question", "")),
        pending_plan_text=None,
        pending_options=options,
        output_offset=log.decision_output_offset,
        checkpoint=checkpoint,
    )
    return None


async def _finish_question(
    db_session: AsyncSession,
    *,
    node_log_id: uuid.UUID,
    user_input_text: str,
) -> None:
    """Ответ получен: запись снова выполняется, ответ остаётся для `{{node.user_input}}`."""
    node_log = await db_session.get(NodeLog, node_log_id)
    if node_log is None:
        return
    node_log.status = NodeLogStatus.RUNNING
    node_log.user_input_text = user_input_text
    await db_session.commit()


async def _record_plan_decision(
    db_session: AsyncSession,
    *,
    node_log_id: uuid.UUID,
    task_id: uuid.UUID,
    decision: PlanDecisionResult,
) -> None:
    """
    Принятый план меняет режим задачи и открывает этап реализации;
    «Доработать план» возвращает планирование в работу без retry.
    """
    node_log = await db_session.get(NodeLog, node_log_id)
    if node_log is not None:
        node_log.finished_at = datetime.now(UTC)
        node_log.status = NodeLogStatus.SUCCESS if decision.allow else NodeLogStatus.RUNNING
        if decision.allow and decision.updated_permission_mode is not None:
            accept_plan_execution(node_log, mode=decision.updated_permission_mode)
    if decision.allow and decision.updated_permission_mode is not None:
        await _set_task_permission_mode(
            db_session,
            task_id=task_id,
            mode=decision.updated_permission_mode,
        )
    await db_session.commit()


def build_can_use_tool_callback(
    *,
    context: ActiveNodeContext,
    session_factory: Callable[[], AbstractAsyncContextManager[AsyncSession]],
    redis_client: Redis,
    decision_wait_timeout_seconds: float | None = None,
) -> CanUseTool:
    """
    Раздел 9.2, 9.6: единый callback на весь жизненный цикл сессии.

    Режим планирования включает нода `plan_prompt`
    (`services/nodes/dispatch.py`); выход из него — решение пользователя по
    плану, которое callback передаёт сессии через `setMode` и записывает в
    `tasks.current_permission_mode`.
    """
    callback = _PermissionCallback(
        context=context,
        session_factory=session_factory,
        redis_client=redis_client,
        decision_wait_timeout_seconds=decision_wait_timeout_seconds,
    )
    return callback.can_use_tool


PermissionResult = PermissionResultAllow | PermissionResultDeny


@dataclass(slots=True)
class _PermissionCallback:
    context: ActiveNodeContext
    session_factory: Callable[[], AbstractAsyncContextManager[AsyncSession]]
    redis_client: Redis
    decision_wait_timeout_seconds: float | None

    async def can_use_tool(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
        _permission_context: ToolPermissionContext,
    ) -> PermissionResult:
        await require_session_owner()
        context = self.context
        active = context.node_log_id is not None and context.task_id is not None
        # Вопрос тоже отклоняется: ожидание ответа перевело бы запись плана из
        # `success` и затёрло бы решение по плану (раздел 9.3).
        if context.plan_accepted:
            return PermissionResultDeny(message=PLAN_ACCEPTED_TOOL_DENIED, interrupt=False)
        if context.context_only:
            return PermissionResultDeny(message=CONTEXT_ONLY_TOOL_DENIED, interrupt=False)
        # После принятого плана агент сам вызывает ExitPlanMode/EnterPlanMode, и это
        # не повод снова просить решение (раздел 9.5). Окно плана остаётся у ноды
        # `plan_prompt` и у чата, где плана в прогоне ещё не принимали (раздел 14.4).
        if (
            tool_name in (EXIT_PLAN_MODE_TOOL, ENTER_PLAN_MODE_TOOL)
            and not context.plan_mode
            and context.task_id is not None
            and await self._plan_already_accepted(context.task_id)
        ):
            logger.info(
                "plan_review_skipped",
                task_id=str(context.task_id),
                tool_name=tool_name,
            )
            return PermissionResultDeny(message=PLANNING_NOT_ACTIVE_DENIED, interrupt=False)
        if tool_name in INTERCEPTED_TOOLS:
            if not active:
                return PermissionResultDeny(message=NO_ACTIVE_NODE_DENIED)
            if tool_name == EXIT_PLAN_MODE_TOOL:
                return await self._review_plan(tool_input)
            return await self._answer_questions(tool_input)
        if context.plan_mode:
            return PermissionResultDeny(message=PLAN_MODE_WRITE_DENIED, interrupt=False)
        if not active:
            return PermissionResultAllow()
        assert context.task_id is not None
        async with self.session_factory() as db_session:
            mode = await _task_permission_mode(db_session, task_id=context.task_id)
        if mode is not PermissionMode.DEFAULT:
            # Раздел 3.1: пока пользователь не выбрал «подтверждать каждое
            # действие», задача работает автономно.
            return PermissionResultAllow()
        return await self._approve_action(tool_name, tool_input)

    async def _plan_already_accepted(self, task_id: uuid.UUID) -> bool:
        async with self.session_factory() as db_session:
            return await plan_accepted_in_run(db_session, task_id)

    async def _await_decision(
        self,
        *,
        awaiting_status: TaskStatus,
        question: str | None,
        plan_text: str | None,
        options: list[dict[str, str]],
        questionnaire: JsonValue | None = None,
    ) -> str | None:
        """Решение пользователя в виджете (9.6); `None` — истёк таймаут ожидания."""
        context = self.context
        assert context.node_log_id is not None and context.task_id is not None
        node_log_id, task_id = context.node_log_id, context.task_id
        resume_status: TaskStatus | None = None
        # Регистрация — до первого изменения в БД: прерванный в любой момент
        # ход (`cancel_decision_wait`) проходит через `finally` ниже. Статус
        # возврата запоминается до перехода: отмена может прийти уже после
        # коммита перехода, а лишний возврат безопасен — это compare-and-swap.
        context.track_decision_wait()
        try:
            async with subscribe_task_signal(self.redis_client, task_id) as signals:
                async with self.session_factory() as db_session:
                    resume_status = await resumable_decision_status(db_session, task_id=task_id)
                    await _mark_awaiting_decision(
                        db_session,
                        node_log_id=node_log_id,
                        pending_question=question,
                        pending_plan_text=plan_text,
                        pending_options=options,
                        output_offset=context.output_offset(),
                        checkpoint=_decision_checkpoint(
                            resume_status=resume_status,
                            awaiting_status=awaiting_status,
                            manual_request_id=context.manual_request_id,
                            questionnaire=questionnaire,
                        ),
                    )
                    if resume_status is not None:
                        await enter_decision_status(
                            db_session,
                            task_id=task_id,
                            resume_status=resume_status,
                            awaiting_status=awaiting_status,
                        )
                logger.info("awaiting_user_decision", node_log_id=str(node_log_id))
                return await _wait_for_resolution(
                    session_factory=self.session_factory,
                    signals=signals,
                    node_log_id=node_log_id,
                    timeout=self.decision_wait_timeout_seconds,
                )
        finally:
            # И после решения, и после таймаута, и при отмене хода (таймаут
            # ноды, «Остановить» — `cancel_decision_wait`) задача не должна
            # остаться в ожидании.
            context.untrack_decision_wait()
            if resume_status is not None:
                await require_session_owner()
                async with self.session_factory() as db_session:
                    await leave_decision_status(
                        db_session,
                        task_id=task_id,
                        awaiting_status=awaiting_status,
                        resume_status=resume_status,
                    )

    async def _finish_question(self, user_input_text: str) -> None:
        assert self.context.node_log_id is not None
        async with self.session_factory() as db_session:
            await _finish_question(
                db_session,
                node_log_id=self.context.node_log_id,
                user_input_text=user_input_text,
            )

    async def _answer_questions(self, tool_input: dict[str, Any]) -> PermissionResult:
        questions = [item for item in tool_input.get("questions") or [] if isinstance(item, dict)]
        if not questions:
            return PermissionResultDeny(message=NO_QUESTIONS_DENIED)
        answers: dict[str, str] = {}
        index = 0
        while index < len(questions):
            question = questions[index]
            text = str(question.get("question", ""))
            options = _question_options(question)
            resolution = await self._await_decision(
                awaiting_status=TaskStatus.AWAITING_INPUT,
                question=text,
                plan_text=None,
                options=[*options, {"id": PREVIOUS_QUESTION_OPTION, "label": "Назад"}]
                if index
                else options,
                questionnaire={"questions": questions, "index": index, "answers": answers},
            )
            if resolution is None:
                return PermissionResultDeny(message=DECISION_TIMEOUT_DENIED)
            if index and resolution == PREVIOUS_QUESTION_OPTION:
                index -= 1
                continue
            answers[text] = answer_from_resolution(resolution, options)
            index += 1
        await self._finish_question("\n".join(f"{q}: {a}" for q, a in answers.items()))
        return PermissionResultAllow(updated_input={**tool_input, "answers": answers})

    async def _approve_action(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
    ) -> PermissionResult:
        resolution = await self._await_decision(
            awaiting_status=TaskStatus.AWAITING_INPUT,
            question=describe_tool_call(tool_name, tool_input),
            plan_text=None,
            options=TOOL_APPROVAL_OPTIONS,
        )
        if resolution is None:
            return PermissionResultDeny(message=DECISION_TIMEOUT_DENIED)
        option_id, feedback_text = parse_decision(resolution)
        await self._finish_question(resolution)
        if option_id == TOOL_APPROVAL_ALLOW:
            return PermissionResultAllow()
        message = TOOL_DENIED_BY_USER
        if feedback_text:
            message = f"{message}: {feedback_text}"
        return PermissionResultDeny(message=message, interrupt=False)

    async def _review_plan(self, tool_input: dict[str, Any]) -> PermissionResult:
        context = self.context
        assert context.node_log_id is not None and context.task_id is not None
        plan_text = tool_input.get("plan")
        if not isinstance(plan_text, str) or not plan_text.strip():
            return PermissionResultDeny(
                message=EMPTY_PLAN_DENIED,
                interrupt=False,
            )
        async with self.session_factory() as db_session:
            auto_accept = await db_session.scalar(
                sa.select(Task.auto_accept_plan).where(Task.id == context.task_id)
            )
        if auto_accept:
            async with self.session_factory() as db_session:
                await _record_plan_auto_accept(
                    db_session,
                    node_log_id=context.node_log_id,
                    task_id=context.task_id,
                    plan_text=plan_text,
                    output_offset=context.output_offset(),
                )
            logger.info("plan_auto_accepted", node_log_id=str(context.node_log_id))
            return self._finish_plan_turn()
        resolution = await self._await_decision(
            awaiting_status=TaskStatus.PLAN_REVIEW,
            question=None,
            plan_text=plan_text,
            options=DEFAULT_PLAN_OPTIONS,
        )
        if resolution is None:
            return PermissionResultDeny(message=DECISION_TIMEOUT_DENIED)
        option_id, feedback_text = parse_decision(resolution)
        decision = apply_plan_decision(option_id, feedback_text=feedback_text)
        async with self.session_factory() as db_session:
            await _record_plan_decision(
                db_session,
                node_log_id=context.node_log_id,
                task_id=context.task_id,
                decision=decision,
            )
        if not decision.allow:
            return PermissionResultDeny(
                message=plan_revise_message(decision.feedback_text),
                interrupt=False,
            )
        return self._finish_plan_turn()

    def _finish_plan_turn(self) -> PermissionResult:
        """
        План принят: заканчивается только ход планирования. Диспетчер
        переключает режим и начинает реализацию внутри той же ноды.
        """
        interrupt = self.context.plan_mode
        self.context.plan_mode = False
        self.context.plan_accepted = True
        return PermissionResultDeny(message=PLAN_ACCEPTED_MESSAGE, interrupt=interrupt)
