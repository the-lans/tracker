"""Оркестратор пайплайна (раздел 11, 13 ТЗ).

Не меняет `tasks.status`/`tasks.last_failed_order_index` напрямую — раздел
14.3 консолидирует переходы статуса задачи в отдельный сервис
(``services/task_status.py``, этап 9 плана реализации). Здесь возвращается
только исход прогона (`PipelineRunOutcome`), которым пользуется вызывающий
код (будущая точка входа Celery-таска, владеющего сессией — архитектурное
решение А плана реализации).
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from claude_agent_sdk import ClaudeSDKError

from app_logging.config import get_logger
from db.models.enums import NodeLogStatus, NodeLogTriggerType, NodeType
from db.models.logs import NodeLog
from db.models.pipelines import Node
from services.failure_classification import is_transient_sdk_exception
from services.node_history import load_node_context_history
from services.node_runs import apply_node_outcome, mark_node_log_stopped, start_node_log
from services.nodes.clear_context import ensure_clear_context_allowed
from services.nodes.dispatch import (
    NodeExecutionOutcome,
    execute_node,
    logged_prompt,
    record_sdk_failure,
    resolve_node_prompt_or_none,
    resolve_script_env_or_none,
    sent_prompt,
)
from services.session_context import forget_task_session
from services.system_settings import resolve_runner_image
from services.task_control import TaskControlCommand, read_task_control, run_stoppable
from services.task_nodes import load_task_node_rows

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Iterator
    from pathlib import Path

    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncSession

    from clients.claude_agent import ClaudeCodeSession
    from db.models.pipelines import TaskNode
    from db.models.tasks import Task
    from services.plan_mode import ActiveNodeContext

_LOG_SOURCE = "pipeline_orchestrator"
logger = get_logger(_LOG_SOURCE)

# Переподключение сессии после падения процесса CLI (раздел 17.3): её
# передаёт владелец сессии — воркер задачи (правило 16 CLAUDE.md).
type SessionRecovery = Callable[[], Awaitable[None]]


def compute_retry_delay_seconds(attempt_number: int, base_delay_seconds: int) -> float:
    """Экспоненциальный рост от `retry_base_delay_seconds` (раздел 11.7)."""
    return float(base_delay_seconds * (2 ** (attempt_number - 1)))


def _remember_session_id(task: Task, claude_session: ClaudeCodeSession) -> None:
    """Раздел 6.1: `session_id` сохраняется сразу после создания сессии —
    по нему перезапуск после `failed` продолжает ту же сессию (resume).
    Коммитится вместе с итогом ноды."""
    if claude_session.session_id is not None and task.session_id != claude_session.session_id:
        task.session_id = claude_session.session_id
        logger.info("session_id_saved", task_id=str(task.id), session_id=task.session_id)


@dataclass(frozen=True, slots=True)
class NodeRunOutcome:
    node_log: NodeLog
    success: bool
    # Кнопка «Остановить» (раздел 14.2) — не сбой ноды: ретрая нет.
    stopped: bool = False


class CheckpointDecision(StrEnum):
    CONTINUE = "continue"
    STOP = "stop"


# Вызывается перед каждой включённой нодой с её `order_index`: здесь
# владелец сессии обрабатывает очередь ручных запросов (раздел 7.3),
# паузу и остановку (раздел 14.2), конфликт ребейза (раздел 14).
type Checkpoint = Callable[[int], Awaitable[CheckpointDecision]]


@dataclass(frozen=True, slots=True)
class StopGuard:
    """Позволяет прервать идущую ноду командой `stop` (раздел 14.2)."""

    redis_client: Redis
    task_id: uuid.UUID

    async def is_stop_requested(self) -> bool:
        command = await read_task_control(self.redis_client, self.task_id)
        return command is TaskControlCommand.STOP


async def run_node_execution(
    execution: Awaitable[NodeExecutionOutcome],
    *,
    node_type: NodeType | None,
    claude_session: ClaudeCodeSession,
    stop_guard: StopGuard | None,
    is_stop_requested: Callable[[], Awaitable[bool]] | None = None,
) -> NodeExecutionOutcome | None:
    """`None` — выполнение остановлено пользователем.

    Для LLM-нод прерывается ход сессии; script-ноде достаточно отмены
    корутины — контейнер останавливает `run_script_node`.
    """
    if stop_guard is None:
        return await execution

    async def abort() -> None:
        if node_type is not NodeType.SCRIPT:
            await claude_session.abort_turn()

    return await run_stoppable(
        execution,
        redis_client=stop_guard.redis_client,
        task_id=stop_guard.task_id,
        is_stop_requested=is_stop_requested or stop_guard.is_stop_requested,
        on_stop=abort,
    )


async def run_pipeline_node_with_retry(
    db_session: AsyncSession,
    *,
    task: Task,
    node: Node,
    claude_session: ClaudeCodeSession,
    repos_path: Path,
    active_node_context: ActiveNodeContext | None = None,
    stop_guard: StopGuard | None = None,
    recover_session: SessionRecovery | None = None,
) -> NodeRunOutcome:
    """Одна нода пайплайна, с retry (раздел 11.7).

    Каждая попытка — ОТДЕЛЬНАЯ запись `node_logs` (раздел 13.4: "история
    не перезаписывается"), а не обновление одной и той же строки.
    Script-ноды пересоздают контейнер с нуля на каждой попытке (уже так,
    поскольку `execute_script_node` каждый раз запускает новый контейнер);
    `plain_prompt`/`slash_command` переиспользуют ту же активную сессию
    (`claude_session` — один и тот же объект на все попытки).

    ``active_node_context`` — мост к callback'у разрешений SDK
    (`services/plan_mode.py`), нужен только для `plan_prompt`: выставляется
    ПЕРЕД отправкой промта, чтобы callback знал, какую запись `node_logs`
    обновлять при вызове `ExitPlanMode`/`AskUserQuestion`.
    """
    attempt = 1
    while True:
        node_log, outcome = await _run_pipeline_attempt(
            db_session,
            task=task,
            node=node,
            attempt=attempt,
            claude_session=claude_session,
            repos_path=repos_path,
            active_node_context=active_node_context,
            stop_guard=stop_guard,
        )
        if outcome is None:
            logger.info("node_stopped_by_user", node_id=str(node.id), attempt=attempt)
            return NodeRunOutcome(node_log=node_log, success=False, stopped=True)
        final = await _final_attempt_outcome(
            node_log=node_log,
            outcome=outcome,
            node=node,
            attempt=attempt,
            stop_guard=stop_guard,
            can_recover_session=recover_session is not None,
        )
        if final is not None:
            return final
        await _prepare_retry(
            outcome,
            node=node,
            attempt=attempt,
            recover_session=recover_session,
        )
        attempt += 1


async def _run_pipeline_attempt(
    db_session: AsyncSession,
    *,
    task: Task,
    node: Node,
    attempt: int,
    claude_session: ClaudeCodeSession,
    repos_path: Path,
    active_node_context: ActiveNodeContext | None,
    stop_guard: StopGuard | None,
) -> tuple[NodeLog, NodeExecutionOutcome | None]:
    """
    Одна попытка — своя запись `node_logs`, итог зафиксирован в БД;
    ``None`` вместо итога — остановка пользователем.
    """
    history = await load_node_context_history(db_session, task)
    prompt = await resolve_node_prompt_or_none(db_session, node=node, task=task, history=history)
    node_log = await start_node_log(
        db_session,
        NodeLog(
            task_id=task.id,
            node_id=node.id,
            trigger_type=NodeLogTriggerType.PIPELINE,
            attempt_number=attempt,
            rendered_prompt=logged_prompt(node, prompt),
        ),
    )
    if active_node_context is not None:
        active_node_context.activate(
            node_log_id=node_log.id,
            task_id=task.id,
            auto_accept_plan=task.auto_accept_plan,
            # Раздел 9.1: пока план не принят, изменения запрещены.
            plan_mode=node.node_type is NodeType.PLAN_PROMPT,
        )

    outcome = await _run_attempt(
        run_node_execution(
            execute_node(
                node,
                prompt=sent_prompt(prompt),
                claude_session=claude_session,
                repos_path=repos_path,
                timeout_seconds=node.timeout_seconds,
                db_session=db_session,
                node_log_id=node_log.id,
                runner_image=await resolve_runner_image(db_session, node),
                script_env=await resolve_script_env_or_none(db_session, node=node, task=task),
            ),
            node_type=node.node_type,
            claude_session=claude_session,
            stop_guard=stop_guard,
        ),
        node_id=node.id,
        claude_session=claude_session,
    )

    _remember_session_id(task, claude_session)
    if outcome is None:
        mark_node_log_stopped(node_log, node_type=node.node_type, claude_session=claude_session)
        await db_session.commit()
        return node_log, None
    apply_node_outcome(node_log, outcome)
    await db_session.commit()
    await record_sdk_failure(outcome, task_id=task.id, node_id=node.id, source=_LOG_SOURCE)
    return node_log, outcome


async def _final_attempt_outcome(
    *,
    node_log: NodeLog,
    outcome: NodeExecutionOutcome,
    node: Node,
    attempt: int,
    stop_guard: StopGuard | None,
    can_recover_session: bool,
) -> NodeRunOutcome | None:
    """Итог ноды после попытки; ``None`` — попытку нужно повторить."""
    if outcome.success:
        logger.info("node_succeeded", node_id=str(node.id), attempt=attempt)
        return NodeRunOutcome(node_log=node_log, success=True)

    if not outcome.is_transient or (outcome.session_lost and not can_recover_session):
        # Раздел 17.3: постоянный сбой повтором не лечится — задача
        # сразу уходит в `failed` с уведомлением автора.
        logger.warning(
            "node_failed_permanent",
            node_id=str(node.id),
            attempt=attempt,
            error=outcome.error_message,
        )
        return NodeRunOutcome(node_log=node_log, success=False)

    if attempt >= node.max_retries:
        logger.warning(
            "node_failed_exhausted_retries",
            node_id=str(node.id),
            attempts=attempt,
            error=outcome.error_message,
        )
        return NodeRunOutcome(node_log=node_log, success=False)

    if stop_guard is not None and await stop_guard.is_stop_requested():
        # Остановка, пришедшая вместе со сбоем, — повторять ноду незачем.
        return NodeRunOutcome(node_log=node_log, success=False, stopped=True)
    return None


async def _prepare_retry(
    outcome: NodeExecutionOutcome,
    *,
    node: Node,
    attempt: int,
    recover_session: SessionRecovery | None,
) -> None:
    """Пауза перед повтором (раздел 11.7) и переподключение упавшей сессии."""
    delay = compute_retry_delay_seconds(attempt, node.retry_base_delay_seconds)
    logger.warning(
        "node_retry_scheduled",
        node_id=str(node.id),
        attempt=attempt,
        delay_seconds=delay,
        error=outcome.error_message,
    )
    await asyncio.sleep(delay)
    if outcome.session_lost and recover_session is not None:
        # Сбой переподключения уходит выше: воркер переведёт задачу в
        # `failed` (`services/task_status.py::fail_task_after_error`).
        await recover_session()
        logger.info("session_recovered_for_retry", node_id=str(node.id), attempt=attempt)


async def _run_attempt(
    execution: Awaitable[NodeExecutionOutcome | None],
    *,
    node_id: uuid.UUID,
    claude_session: ClaudeCodeSession,
) -> NodeExecutionOutcome | None:
    """
    Исключение SDK посреди хода — неуспешная попытка, а не падение прогона;
    полученная до сбоя часть ответа сохраняется (раздел 6.4).
    """
    try:
        return await execution
    except ClaudeSDKError as exc:
        logger.exception("node_session_failed", node_id=str(node_id))
        return NodeExecutionOutcome(
            success=False,
            llm_output_text=claude_session.take_partial_turn_text(),
            error_message=f"Сбой сессии Claude Code: {exc}",
            is_transient=is_transient_sdk_exception(exc),
            session_lost=True,
        )


@dataclass(frozen=True, slots=True)
class PipelineRunOutcome:
    completed: bool
    failed_order_index: int | None = None
    # Раздел 11.5: clear_context обрывает текущую сессию — продолжение
    # пайплайна требует новой сессии, что вне ответственности этого модуля
    # (владение сессией — Celery-таск, архитектурное решение А плана).
    # Вызывающий код обязан переподключиться и вызвать run_pipeline снова
    # с ``start_after_order_index=context_cleared_at_order_index``.
    context_cleared_at_order_index: int | None = None
    # Остановка пользователем (раздел 14.2): ``failed_order_index`` —
    # нода, с которой продолжит «Перезапустить с текущей ноды».
    stopped: bool = False


def _nodes_to_run(
    rows: list[tuple[TaskNode, Node]],
    *,
    start_after_order_index: int | None,
) -> Iterator[tuple[TaskNode, Node]]:
    """
    Ноды после точки продолжения; отключённые пропускаются без записи
    `node_logs` (раздел 13.3).
    """
    for task_node, node in rows:
        if start_after_order_index is not None and task_node.order_index <= start_after_order_index:
            continue
        if not task_node.is_enabled:
            logger.info(
                "node_skipped_disabled",
                node_id=str(node.id),
                order_index=task_node.order_index,
            )
            continue
        yield task_node, node


async def _clear_session_context(
    db_session: AsyncSession,
    *,
    task: Task,
    node: Node,
    claude_session: ClaudeCodeSession,
) -> None:
    """
    Нода `clear_context` (раздел 11.5): сессия обрывается, новая начнётся с чистого листа.
    """
    await ensure_clear_context_allowed(db_session, task.id)
    await claude_session.disconnect()
    forget_task_session(task)
    now = datetime.now(UTC)
    # Успешная запись нужна инварианту перехода в `done` (раздел 17.5):
    # без неё пайплайн с clear_context никогда бы не завершился.
    db_session.add(
        NodeLog(
            task_id=task.id,
            node_id=node.id,
            trigger_type=NodeLogTriggerType.PIPELINE,
            status=NodeLogStatus.SUCCESS,
            started_at=now,
            finished_at=now,
        ),
    )
    await db_session.commit()


async def run_pipeline(
    db_session: AsyncSession,
    *,
    task: Task,
    claude_session: ClaudeCodeSession,
    repos_path: Path,
    start_after_order_index: int | None = None,
    active_node_context: ActiveNodeContext | None = None,
    checkpoint: Checkpoint | None = None,
    stop_guard: StopGuard | None = None,
    recover_session: SessionRecovery | None = None,
) -> PipelineRunOutcome:
    """Итерирует `task_nodes` в порядке `order_index` (раздел 13.3).

    Отключённые ноды (``is_enabled=false``) пропускаются без создания
    записи `node_logs`. ``start_after_order_index`` — для продолжения после
    `clear_context` или перезапуска с точки сбоя ("Перезапустить с текущей
    ноды", раздел 14.2): ноды с ``order_index <= start_after_order_index``
    уже имеют зафиксированную историю и повторно не выполняются.
    ``active_node_context``/``stop_guard``/``recover_session`` — см.
    `run_pipeline_node_with_retry`.
    ``checkpoint`` вызывается перед каждой включённой нодой; `STOP`
    завершает прогон до её выполнения.
    """
    rows = await load_task_node_rows(db_session, task.id)

    for task_node, node in _nodes_to_run(rows, start_after_order_index=start_after_order_index):
        if checkpoint is not None:
            decision = await checkpoint(task_node.order_index)
            if decision is CheckpointDecision.STOP:
                logger.info("pipeline_stopped_at_checkpoint", order_index=task_node.order_index)
                return PipelineRunOutcome(
                    completed=False,
                    failed_order_index=task_node.order_index,
                    stopped=True,
                )

        if node.node_type is NodeType.CLEAR_CONTEXT:
            await _clear_session_context(
                db_session,
                task=task,
                node=node,
                claude_session=claude_session,
            )
            logger.info("session_context_cleared", order_index=task_node.order_index)
            return PipelineRunOutcome(
                completed=False,
                context_cleared_at_order_index=task_node.order_index,
            )

        outcome = await run_pipeline_node_with_retry(
            db_session,
            task=task,
            node=node,
            claude_session=claude_session,
            repos_path=repos_path,
            active_node_context=active_node_context,
            stop_guard=stop_guard,
            recover_session=recover_session,
        )
        if not outcome.success:
            return PipelineRunOutcome(
                completed=False,
                failed_order_index=task_node.order_index,
                stopped=outcome.stopped,
            )

    return PipelineRunOutcome(completed=True)
