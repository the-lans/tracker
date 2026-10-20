"""
Саммари родительской задачи при старте дочерней (`tasks.use_parent_summary`, раздел 3.1 ТЗ).

Решение 2026-10-20: историю пересказывает сессия самого родителя — по
запросу, когда стартует дочерняя задача. Пересказ сохраняется отдельным
артефактом (`task_parent_summaries`) и уходит первым сообщением новой
сессии дочерней задачи.

Откуда берётся пересказ:

- сессией родителя сейчас владеет его воркер (статус из
  `SESSION_ACTIVE_STATUSES`) — запрос встаёт в очередь ручных запросов
  родителя (правило 1: одна сессия — один запрос за раз), дочерняя ждёт;
- родитель свободен, но сессия у него есть — ход выполняется в ответвлении
  его сессии (`fork_session`): история родителя не меняется, гонки с его
  воркером нет;
- сессии нет — дочерняя задача стартует без саммари, с пометкой в ленте.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import sqlalchemy as sa
from claude_agent_sdk import PermissionResultDeny

from app_logging.config import get_logger
from db.models.enums import (
    ManualRequestStatus,
    ManualRequestType,
    NodeLogStatus,
    NodeLogTriggerType,
    ParentSummaryStatus,
)
from db.models.logs import NodeLog
from db.models.prompts import TaskManualRequestQueue
from db.models.tasks import Task, TaskParentSummary
from services.nodes.dispatch import execute_llm_node_with_timeout
from services.task_signal import publish_task_signal, wait_for_task_signal
from services.task_status import SESSION_ACTIVE_STATUSES

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from claude_agent_sdk.types import ToolPermissionContext
    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncSession

    from clients.claude_agent import ClaudeCodeSession
    from services.plan_mode import ActiveNodeContext

logger = get_logger("parent_summary")

# Страховка от потерянного сигнала, пока дочерняя ждёт очередь родителя.
_WAIT_POLL_SECONDS = 30.0
_CLOSED_REQUEST_STATUSES = frozenset({ManualRequestStatus.DONE, ManualRequestStatus.CANCELLED})

SUMMARY_REQUEST_PROMPT = (
    "Кратко перескажи историю этой задачи для дочерней задачи {child_code} «{child_title}»: "
    "цель, принятые решения и утверждённый план, что сделано, что осталось, важные нюансы и "
    "ограничения. Ответь только пересказом, ничего не меняй в файлах и не запускай инструменты."
)
DELIVERY_MESSAGE = (
    "Контекст родительской задачи {parent_code} «{parent_title}» — пересказ её сессии:\n\n"
    "{summary}\n\nУчитывай его в работе над этой задачей."
)
REASON_NO_SESSION = "у родительской задачи нет сессии"
REASON_PARENT_MISSING = "родительская задача не найдена"
REASON_SUMMARY_FAILED = "сессия родителя не смогла составить пересказ"


def build_summary_request_prompt(child: Task) -> str:
    return SUMMARY_REQUEST_PROMPT.format(child_code=child.code, child_title=child.title)


def needs_parent_summary(task: Task) -> bool:
    return task.use_parent_summary and task.parent_task_id is not None


async def deny_all_tools(
    tool_name: str,
    _tool_input: dict[str, Any],
    _context: ToolPermissionContext,
) -> PermissionResultDeny:
    """Ответвление сессии родителя только пересказывает — без инструментов."""
    return PermissionResultDeny(message=f"Пересказ выполняется без инструментов ({tool_name})")



def _mark_unavailable(summary: TaskParentSummary, reason: str) -> None:
    summary.status = ParentSummaryStatus.UNAVAILABLE
    summary.unavailable_reason = reason
    summary.completed_at = datetime.now(UTC)


def _mark_ready(summary: TaskParentSummary, text: str) -> None:
    summary.status = ParentSummaryStatus.READY
    summary.summary_text = text
    summary.completed_at = datetime.now(UTC)


async def get_or_request_parent_summary(
    db_session: AsyncSession,
    *,
    child: Task,
    redis_client: Redis,
) -> TaskParentSummary:
    """Строка артефакта дочерней задачи; при первом обращении — запрос пересказа."""
    existing = await db_session.scalar(
        sa.select(TaskParentSummary).where(TaskParentSummary.child_task_id == child.id),
    )
    if existing is not None:
        return existing
    assert child.parent_task_id is not None
    summary = TaskParentSummary(
        parent_task_id=child.parent_task_id,
        child_task_id=child.id,
        status=ParentSummaryStatus.PENDING,
    )
    db_session.add(summary)
    parent = await db_session.get(Task, child.parent_task_id)
    if parent is None:
        _mark_unavailable(summary, REASON_PARENT_MISSING)
    elif parent.status in SESSION_ACTIVE_STATUSES:
        request = TaskManualRequestQueue(
            task_id=parent.id,
            request_type=ManualRequestType.PARENT_SUMMARY,
            raw_prompt_text=build_summary_request_prompt(child),
            requested_by=child.created_by,
            status=ManualRequestStatus.QUEUED,
            requested_at=datetime.now(UTC),
        )
        db_session.add(request)
        await db_session.flush()
        summary.manual_request_id = request.id
    elif parent.session_id is None:
        _mark_unavailable(summary, REASON_NO_SESSION)
    await db_session.commit()
    if summary.manual_request_id is not None:
        await publish_task_signal(redis_client, child.parent_task_id)
    logger.info(
        "parent_summary_requested",
        task_id=str(child.id),
        parent_task_id=str(child.parent_task_id),
        via_parent_queue=summary.manual_request_id is not None,
        status=summary.status.value,
    )
    return summary


async def _release_stuck_request(db_session: AsyncSession, summary: TaskParentSummary) -> None:
    """
    Запрос в очереди родителя больше не выполнится — пересказ делается в
    ответвлении сессии родителя (или недоступен, если сессии нет).
    """
    assert summary.manual_request_id is not None
    request = await db_session.get(
        TaskManualRequestQueue,
        summary.manual_request_id,
        populate_existing=True,
    )
    parent = await db_session.get(Task, summary.parent_task_id, populate_existing=True)
    if request is None or parent is None:
        summary.manual_request_id = None
        await db_session.commit()
        return
    parent_left_session = parent.status not in SESSION_ACTIVE_STATUSES
    if request.status is ManualRequestStatus.QUEUED and parent_left_session:
        request.status = ManualRequestStatus.CANCELLED
        request.processed_at = datetime.now(UTC)
    if request.status in _CLOSED_REQUEST_STATUSES:
        # Истёк в очереди, родитель ушёл из активных статусов или упал на нём.
        summary.manual_request_id = None
        logger.info("parent_summary_request_released", task_id=str(summary.child_task_id))
    await db_session.commit()


async def wait_for_parent_summary(
    db_session: AsyncSession,
    *,
    summary: TaskParentSummary,
    redis_client: Redis,
    is_stop_requested: Callable[[], Awaitable[bool]],
) -> bool:
    """
    Ждёт, пока очередь родителя выполнит пересказ; `False` — дочернюю
    задачу остановили во время ожидания.

    После возврата `True` артефакт либо готов/недоступен, либо уже не связан
    с очередью родителя — тогда пересказ делается в ответвлении его сессии.
    """
    while True:
        await db_session.refresh(summary)
        if summary.status is not ParentSummaryStatus.PENDING or summary.manual_request_id is None:
            return True
        await _release_stuck_request(db_session, summary)
        if summary.manual_request_id is None:
            return True
        if await is_stop_requested():
            return False
        await wait_for_task_signal(redis_client, summary.child_task_id, timeout=_WAIT_POLL_SECONDS)


async def _run_summary_turn(
    db_session: AsyncSession,
    *,
    parent: Task,
    prompt: str,
    triggered_by: uuid.UUID | None,
    claude_session: ClaudeCodeSession,
    timeout_seconds: int,
    active_node_context: ActiveNodeContext | None,
) -> str | None:
    """Ход пересказа в сессии родителя; запись — в ленте родителя."""
    node_log = NodeLog(
        task_id=parent.id,
        trigger_type=NodeLogTriggerType.SUMMARY_FOR_CHILD,
        triggered_by=triggered_by,
        rendered_prompt=prompt,
        status=NodeLogStatus.RUNNING,
        started_at=datetime.now(UTC),
    )
    db_session.add(node_log)
    await db_session.commit()
    if active_node_context is not None:
        active_node_context.activate(node_log_id=node_log.id, task_id=parent.id)
    outcome = await execute_llm_node_with_timeout(
        claude_session,
        prompt,
        timeout_seconds=timeout_seconds,
    )
    node_log.finished_at = datetime.now(UTC)
    node_log.llm_output_text = outcome.llm_output_text
    succeeded = outcome.success and bool(outcome.llm_output_text)
    node_log.status = NodeLogStatus.SUCCESS if succeeded else NodeLogStatus.FAILED
    await db_session.commit()
    return outcome.llm_output_text if succeeded else None


async def run_parent_summary_request(
    db_session: AsyncSession,
    *,
    parent: Task,
    request: TaskManualRequestQueue,
    claude_session: ClaudeCodeSession,
    redis_client: Redis,
    timeout_seconds: int,
    active_node_context: ActiveNodeContext | None,
) -> None:
    """Запрос `parent_summary` из очереди родителя — в его живой сессии."""
    assert request.raw_prompt_text is not None
    summary = await db_session.scalar(
        sa.select(TaskParentSummary).where(TaskParentSummary.manual_request_id == request.id),
    )
    text = await _run_summary_turn(
        db_session,
        parent=parent,
        prompt=request.raw_prompt_text,
        triggered_by=request.requested_by,
        claude_session=claude_session,
        timeout_seconds=timeout_seconds,
        active_node_context=active_node_context,
    )
    if summary is None:
        logger.warning("parent_summary_artifact_missing", request_id=str(request.id))
        return
    if text is None:
        _mark_unavailable(summary, REASON_SUMMARY_FAILED)
    else:
        _mark_ready(summary, text)
    await db_session.commit()
    await publish_task_signal(redis_client, summary.child_task_id)


async def summarize_parent_in_fork(
    db_session: AsyncSession,
    *,
    summary: TaskParentSummary,
    child: Task,
    parent: Task,
    claude_session: ClaudeCodeSession,
    timeout_seconds: int,
) -> None:
    """Ход пересказа в ответвлении сессии родителя (`fork_session`)."""
    text = await _run_summary_turn(
        db_session,
        parent=parent,
        prompt=build_summary_request_prompt(child),
        triggered_by=child.created_by,
        claude_session=claude_session,
        timeout_seconds=timeout_seconds,
        active_node_context=None,
    )
    if text is None:
        _mark_unavailable(summary, REASON_SUMMARY_FAILED)
    else:
        _mark_ready(summary, text)
    await db_session.commit()


async def mark_parent_summary_unavailable(
    db_session: AsyncSession,
    *,
    summary: TaskParentSummary,
    reason: str,
) -> None:
    _mark_unavailable(summary, reason)
    await db_session.commit()


async def deliver_parent_summary(
    db_session: AsyncSession,
    *,
    child: Task,
    summary: TaskParentSummary,
    claude_session: ClaudeCodeSession,
    timeout_seconds: int,
    active_node_context: ActiveNodeContext | None,
) -> None:
    """
    Первое сообщение новой сессии дочерней задачи; без пересказа — только
    пометка в её ленте.
    """
    parent = await db_session.get(Task, summary.parent_task_id)
    node_log = NodeLog(
        task_id=child.id,
        trigger_type=NodeLogTriggerType.PARENT_SUMMARY,
        status=NodeLogStatus.RUNNING,
        started_at=datetime.now(UTC),
    )
    db_session.add(node_log)
    if summary.status is ParentSummaryStatus.READY and parent is not None:
        assert summary.summary_text is not None
        message = DELIVERY_MESSAGE.format(
            parent_code=parent.code,
            parent_title=parent.title,
            summary=summary.summary_text,
        )
        node_log.rendered_prompt = message
        await db_session.commit()
        if active_node_context is not None:
            active_node_context.activate(node_log_id=node_log.id, task_id=child.id)
        outcome = await execute_llm_node_with_timeout(
            claude_session,
            message,
            timeout_seconds=timeout_seconds,
        )
        node_log.llm_output_text = outcome.llm_output_text
        node_log.status = NodeLogStatus.SUCCESS if outcome.success else NodeLogStatus.FAILED
    else:
        reason = summary.unavailable_reason or REASON_NO_SESSION
        node_log.rendered_prompt = f"Саммари родительской задачи недоступно: {reason}"
        node_log.status = NodeLogStatus.FAILED
    node_log.finished_at = datetime.now(UTC)
    summary.delivered_at = datetime.now(UTC)
    await db_session.commit()
    logger.info(
        "parent_summary_delivered",
        task_id=str(child.id),
        status=summary.status.value,
        node_log_status=node_log.status.value,
    )
