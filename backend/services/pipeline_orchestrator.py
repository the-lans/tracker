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
from typing import TYPE_CHECKING

import sqlalchemy as sa

from app_logging.config import get_logger
from db.models.enums import NodeLogStatus, NodeLogTriggerType, NodeType
from db.models.logs import NodeLog
from db.models.pipelines import Node, TaskNode
from services.nodes.clear_context import ensure_clear_context_allowed
from services.nodes.dispatch import execute_node, resolve_node_prompt_or_none

if TYPE_CHECKING:
    from pathlib import Path

    from sqlalchemy.ext.asyncio import AsyncSession

    from clients.claude_agent import ClaudeCodeSession
    from db.models.tasks import Task
    from services.plan_mode import ActiveNodeContext

logger = get_logger("pipeline_orchestrator")


def compute_retry_delay_seconds(attempt_number: int, base_delay_seconds: int) -> float:
    """Экспоненциальный рост от `retry_base_delay_seconds` (раздел 11.7)."""
    return float(base_delay_seconds * (2 ** (attempt_number - 1)))


async def _load_node_log_history(db_session: AsyncSession, task_id: uuid.UUID) -> list[NodeLog]:
    stmt = (
        sa.select(NodeLog)
        .where(NodeLog.task_id == task_id)
        .order_by(NodeLog.started_at, NodeLog.id)
    )
    return list((await db_session.execute(stmt)).scalars().all())


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


async def run_pipeline_node_with_retry(
    db_session: AsyncSession,
    *,
    task: Task,
    node: Node,
    claude_session: ClaudeCodeSession,
    repos_path: Path,
    active_node_context: ActiveNodeContext | None = None,
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
        history = await _load_node_log_history(db_session, task.id)
        prompt = await resolve_node_prompt_or_none(
            db_session,
            node=node,
            task=task,
            history=history,
        )
        node_log = NodeLog(
            task_id=task.id,
            node_id=node.id,
            trigger_type=NodeLogTriggerType.PIPELINE,
            attempt_number=attempt,
            rendered_prompt=prompt if node.node_type is not NodeType.SLASH_COMMAND else None,
            status=NodeLogStatus.RUNNING,
            started_at=datetime.now(UTC),
        )
        db_session.add(node_log)
        await db_session.commit()

        if active_node_context is not None:
            active_node_context.node_log_id = node_log.id
            active_node_context.task_id = task.id
            active_node_context.auto_accept_plan = task.auto_accept_plan

        outcome = await execute_node(
            node,
            prompt=prompt,
            claude_session=claude_session,
            repos_path=repos_path,
            timeout_seconds=node.timeout_seconds,
            db_session=db_session,
            node_log_id=node_log.id,
        )

        _remember_session_id(task, claude_session)
        node_log.finished_at = datetime.now(UTC)
        node_log.llm_output_text = outcome.llm_output_text
        node_log.script_stdout = outcome.script_stdout
        node_log.script_exit_code = outcome.script_exit_code
        node_log.status = NodeLogStatus.SUCCESS if outcome.success else NodeLogStatus.FAILED
        await db_session.commit()

        if outcome.success:
            logger.info("node_succeeded", node_id=str(node.id), attempt=attempt)
            return NodeRunOutcome(node_log=node_log, success=True)

        if attempt >= node.max_retries:
            logger.warning(
                "node_failed_exhausted_retries",
                node_id=str(node.id),
                attempts=attempt,
                error=outcome.error_message,
            )
            return NodeRunOutcome(node_log=node_log, success=False)

        delay = compute_retry_delay_seconds(attempt, node.retry_base_delay_seconds)
        logger.warning(
            "node_retry_scheduled",
            node_id=str(node.id),
            attempt=attempt,
            delay_seconds=delay,
            error=outcome.error_message,
        )
        await asyncio.sleep(delay)
        attempt += 1


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


async def run_pipeline(
    db_session: AsyncSession,
    *,
    task: Task,
    claude_session: ClaudeCodeSession,
    repos_path: Path,
    start_after_order_index: int | None = None,
    active_node_context: ActiveNodeContext | None = None,
) -> PipelineRunOutcome:
    """Итерирует `task_nodes` в порядке `order_index` (раздел 13.3).

    Отключённые ноды (``is_enabled=false``) пропускаются без создания
    записи `node_logs`. ``start_after_order_index`` — для продолжения после
    `clear_context` или перезапуска с точки сбоя ("Перезапустить с текущей
    ноды", раздел 14.2): ноды с ``order_index <= start_after_order_index``
    уже имеют зафиксированную историю и повторно не выполняются.
    ``active_node_context`` — см. `run_pipeline_node_with_retry`.
    """
    stmt = (
        sa.select(TaskNode, Node)
        .join(Node, Node.id == TaskNode.node_id)
        .where(TaskNode.task_id == task.id)
        .order_by(TaskNode.order_index)
    )
    rows = (await db_session.execute(stmt)).all()

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

        if node.node_type is NodeType.CLEAR_CONTEXT:
            await ensure_clear_context_allowed(db_session, task.id)
            await claude_session.disconnect()
            task.session_id = None
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
        )
        if not outcome.success:
            return PipelineRunOutcome(completed=False, failed_order_index=task_node.order_index)

    return PipelineRunOutcome(completed=True)
