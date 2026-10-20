"""Библиотека промтов, очередь ручных запросов, свободный промт (раздел 7, 8 ТЗ).

API (этап 12) только СОЗДАЁТ запись здесь и публикует Redis-сигнал
(`services.task_signal.publish_task_signal`) — фактическое выполнение
происходит на стороне долгоживущего Celery-таска, владеющего сессией
(архитектурное решение А плана реализации): "сессия свободна -> выполнить
немедленно" и "сессия занята -> в очередь" неразличимы с точки зрения API —
разница только в том, когда оркестратор доберётся до записи (раздел 7.3:
"сразу по завершении текущего занимающего сессию обращения... прежде чем
переходить к следующей ноде пайплайна").

Ни библиотечные, ни свободные промты не проходят через retry (раздел 7.4,
7.5, 11.7: "не применяется... к запускам из библиотеки") — единственная
попытка, таймаут `timeout_seconds` (по умолчанию, раздел 8, — для
свободного промта, у которого нет своей ноды) переводит запись в `failed`.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import sqlalchemy as sa

from app_logging.config import get_logger
from db.models.enums import (
    LibraryPromptRunStatus,
    ManualRequestStatus,
    ManualRequestType,
    NodeLogStatus,
    NodeLogTriggerType,
    NodeType,
)
from db.models.logs import NodeLog
from db.models.pipelines import Node
from db.models.prompts import TaskLibraryPrompt, TaskManualRequestQueue
from db.models.tasks import Task
from services.distributed_lock import LockNotAcquiredError, acquire_task_operation_lock
from services.errors import ConflictError, ValidationError
from services.nodes.dispatch import (
    execute_llm_node_with_timeout,
    execute_node,
    resolve_node_prompt_or_none,
)
from services.notifications import NotificationEvent, notify_task_event
from services.pipeline_orchestrator import StopGuard, run_node_execution
from services.task_control import clear_manual_stop, is_manual_stop_requested
from services.template_context import render_for_task
from services.templating import (
    RenderScope,
    is_slash_command_text,
    validate_template_variables,
)

if TYPE_CHECKING:
    from pathlib import Path

    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncSession

    from clients.claude_agent import ClaudeCodeSession
    from services.plan_mode import ActiveNodeContext

# Раздел 17.5: "Обработка очереди task_manual_request_queue обязана быть
# защищена той же распределённой блокировкой, что и обращения к сессии."
MANUAL_QUEUE_LOCK_OPERATION = "manual_queue"

logger = get_logger("manual_queue")

# Раздел 7.2: "Типы clear_context и plan_prompt для библиотеки бессмысленны
# (это разовые пайплайн-действия) и не должны предлагаться при создании
# библиотечного промта."
LIBRARY_FORBIDDEN_NODE_TYPES = frozenset({NodeType.CLEAR_CONTEXT, NodeType.PLAN_PROMPT})

# Раздел 8 не называет таймаут для свободного промта отдельно (в отличие от
# раздела 7.4 для библиотеки, где используется nodes.timeout_seconds) —
# нода у свободного промта отсутствует. Значение — то же умолчание, что и
# у ноды пайплайна (nodes.timeout_seconds, раздел 3.1).
DEFAULT_FREEFORM_TIMEOUT_SECONDS = 600


async def enqueue_library_prompt_run(
    db_session: AsyncSession,
    *,
    task_library_prompt: TaskLibraryPrompt,
    node: Node,
    requested_by: uuid.UUID,
) -> TaskManualRequestQueue:
    if node.node_type in LIBRARY_FORBIDDEN_NODE_TYPES:
        raise ValidationError(f"Тип ноды {node.node_type} недопустим для библиотеки промтов")
    request = TaskManualRequestQueue(
        task_id=task_library_prompt.task_id,
        request_type=ManualRequestType.LIBRARY_PROMPT,
        node_id=node.id,
        requested_by=requested_by,
        status=ManualRequestStatus.QUEUED,
        requested_at=datetime.now(UTC),
    )
    db_session.add(request)
    task_library_prompt.last_run_status = LibraryPromptRunStatus.QUEUED
    await db_session.commit()
    logger.info(
        "library_prompt_enqueued",
        task_id=str(task_library_prompt.task_id),
        node_id=str(node.id),
    )
    return request


async def enqueue_freeform_prompt_run(
    db_session: AsyncSession,
    *,
    task_id: uuid.UUID,
    raw_prompt_text: str,
    requested_by: uuid.UUID,
) -> TaskManualRequestQueue:
    # Раздел 8.2: "{{node.*}}" недоступны свободному полю ввода — проверяется
    # здесь же, до постановки в очередь, а не только на предпросмотре.
    validate_template_variables(raw_prompt_text, scope=RenderScope.FREEFORM)
    request = TaskManualRequestQueue(
        task_id=task_id,
        request_type=ManualRequestType.FREEFORM_PROMPT,
        raw_prompt_text=raw_prompt_text,
        requested_by=requested_by,
        status=ManualRequestStatus.QUEUED,
        requested_at=datetime.now(UTC),
    )
    db_session.add(request)
    await db_session.commit()
    logger.info("freeform_prompt_enqueued", task_id=str(task_id))
    return request


async def render_freeform_prompt(db_session: AsyncSession, *, task: Task, text: str) -> str:
    """Раздел 8.2: переменные раздела 5 (кроме `{{node.*}}`) подставляются
    непосредственно перед отправкой (5.1); слэш-команда уходит буквально.

    Та же функция отвечает и предпросмотру — пользователь видит ровно то,
    что получит сессия.
    """
    if is_slash_command_text(text):
        return text
    return await render_for_task(db_session, task, text)


async def cancel_manual_request(
    db_session: AsyncSession,
    request: TaskManualRequestQueue,
) -> None:
    """Раздел 7.3: "Пользователь может отменить ещё не обработанный запрос"."""
    if request.status is not ManualRequestStatus.QUEUED:
        raise ConflictError("Запрос уже обрабатывается или завершён — отмена недоступна")
    request.status = ManualRequestStatus.CANCELLED
    request.processed_at = datetime.now(UTC)
    await db_session.commit()


async def _load_node_log_history(db_session: AsyncSession, task_id: uuid.UUID) -> list[NodeLog]:
    stmt = (
        sa.select(NodeLog)
        .where(NodeLog.task_id == task_id)
        .order_by(NodeLog.started_at, NodeLog.id)
    )
    return list((await db_session.execute(stmt)).scalars().all())


def _activate_context(
    active_node_context: ActiveNodeContext | None,
    *,
    node_log: NodeLog,
    task: Task,
) -> None:
    """Вопрос агента во время ручного запроса (раздел 9.6) и потоковый вывод
    (раздел 15.2) адресуются записи этого запроса."""
    if active_node_context is not None:
        active_node_context.activate(
            node_log_id=node_log.id,
            task_id=task.id,
            auto_accept_plan=task.auto_accept_plan,
        )


def _manual_stop_guard(redis_client: Redis, request: TaskManualRequestQueue) -> StopGuard:
    return StopGuard(redis_client=redis_client, task_id=request.task_id)


async def _manual_stop_requested(guard: StopGuard, request: TaskManualRequestQueue) -> bool:
    """Кнопка ■ этого запроса (раздел 7.3) или «Остановить» всей задачи (14.2)."""
    if await is_manual_stop_requested(guard.redis_client, guard.task_id, request.id):
        return True
    return await guard.is_stop_requested()


async def _run_library_prompt(
    db_session: AsyncSession,
    *,
    task: Task,
    request: TaskManualRequestQueue,
    claude_session: ClaudeCodeSession,
    repos_path: Path,
    redis_client: Redis,
    active_node_context: ActiveNodeContext | None,
) -> None:
    assert request.node_id is not None
    node = await db_session.get(Node, request.node_id)
    if node is None:
        message = f"Нода библиотечного промта {request.node_id} не найдена"
        raise ValueError(message)

    task_library_prompt_stmt = sa.select(TaskLibraryPrompt).where(
        TaskLibraryPrompt.task_id == task.id,
        TaskLibraryPrompt.node_id == node.id,
    )
    task_library_prompt = await db_session.scalar(task_library_prompt_stmt)
    if task_library_prompt is not None:
        task_library_prompt.last_run_status = LibraryPromptRunStatus.RUNNING

    history = await _load_node_log_history(db_session, task.id)
    prompt = await resolve_node_prompt_or_none(db_session, node=node, task=task, history=history)
    node_log = NodeLog(
        task_id=task.id,
        node_id=node.id,
        trigger_type=NodeLogTriggerType.LIBRARY_MANUAL,
        triggered_by=request.requested_by,
        rendered_prompt=prompt if node.node_type is not NodeType.SLASH_COMMAND else None,
        status=NodeLogStatus.RUNNING,
        started_at=datetime.now(UTC),
    )
    db_session.add(node_log)
    await db_session.commit()
    _activate_context(active_node_context, node_log=node_log, task=task)

    guard = _manual_stop_guard(redis_client, request)

    async def stop_requested() -> bool:
        return await _manual_stop_requested(guard, request)

    outcome = await run_node_execution(
        execute_node(
            node,
            prompt=prompt,
            claude_session=claude_session,
            repos_path=repos_path,
            timeout_seconds=node.timeout_seconds,
        ),
        node_type=node.node_type,
        claude_session=claude_session,
        stop_guard=guard,
        is_stop_requested=stop_requested,
    )

    node_log.finished_at = datetime.now(UTC)
    if outcome is None:
        node_log.status = NodeLogStatus.STOPPED
        if task_library_prompt is not None:
            task_library_prompt.last_run_status = LibraryPromptRunStatus.STOPPED
            task_library_prompt.last_run_at = node_log.finished_at
        await db_session.commit()
        logger.info("library_prompt_run_stopped", node_id=str(node.id))
        return

    node_log.llm_output_text = outcome.llm_output_text
    node_log.script_stdout = outcome.script_stdout
    node_log.script_exit_code = outcome.script_exit_code
    node_log.status = NodeLogStatus.SUCCESS if outcome.success else NodeLogStatus.FAILED

    if task_library_prompt is not None:
        task_library_prompt.last_run_status = (
            LibraryPromptRunStatus.SUCCESS if outcome.success else LibraryPromptRunStatus.FAILED
        )
        task_library_prompt.last_run_at = node_log.finished_at

    await db_session.commit()
    logger.info(
        "library_prompt_run_finished",
        node_id=str(node.id),
        success=outcome.success,
        error=outcome.error_message,
    )
    if not outcome.success:
        await notify_task_event(
            db_session,
            event=NotificationEvent.LIBRARY_PROMPT_FAILED,
            task=task,
            detail=f"{task.code}: промт «{node.name}» завершился с ошибкой",
        )


async def _run_freeform_prompt(
    db_session: AsyncSession,
    *,
    task: Task,
    request: TaskManualRequestQueue,
    claude_session: ClaudeCodeSession,
    redis_client: Redis,
    active_node_context: ActiveNodeContext | None,
) -> None:
    assert request.raw_prompt_text is not None
    prompt = await render_freeform_prompt(db_session, task=task, text=request.raw_prompt_text)
    node_log = NodeLog(
        task_id=task.id,
        trigger_type=NodeLogTriggerType.FREEFORM_MANUAL,
        triggered_by=request.requested_by,
        rendered_prompt=prompt,
        status=NodeLogStatus.RUNNING,
        started_at=datetime.now(UTC),
    )
    db_session.add(node_log)
    await db_session.commit()
    _activate_context(active_node_context, node_log=node_log, task=task)

    # Свободный промт (раздел 8) — всегда обычный текст, без своей ноды и
    # без понятия node_type: `execute_node` здесь не подходит (ему нужен
    # реальный Node для диспетчеризации script/LLM), вызывается LLM-ветка
    # напрямую.
    guard = _manual_stop_guard(redis_client, request)

    async def stop_requested() -> bool:
        return await _manual_stop_requested(guard, request)

    outcome = await run_node_execution(
        execute_llm_node_with_timeout(
            claude_session,
            prompt,
            timeout_seconds=DEFAULT_FREEFORM_TIMEOUT_SECONDS,
        ),
        node_type=None,
        claude_session=claude_session,
        stop_guard=guard,
        is_stop_requested=stop_requested,
    )

    node_log.finished_at = datetime.now(UTC)
    if outcome is None:
        node_log.status = NodeLogStatus.STOPPED
        await db_session.commit()
        logger.info("freeform_prompt_run_stopped")
        return
    node_log.llm_output_text = outcome.llm_output_text
    node_log.status = NodeLogStatus.SUCCESS if outcome.success else NodeLogStatus.FAILED
    await db_session.commit()
    logger.info(
        "freeform_prompt_run_finished",
        success=outcome.success,
        error=outcome.error_message,
    )


async def _process_single_request(
    db_session: AsyncSession,
    *,
    task: Task,
    request: TaskManualRequestQueue,
    claude_session: ClaudeCodeSession,
    repos_path: Path,
    redis_client: Redis,
    active_node_context: ActiveNodeContext | None,
) -> None:
    request.status = ManualRequestStatus.PROCESSING
    await db_session.commit()

    if request.request_type is ManualRequestType.LIBRARY_PROMPT:
        await _run_library_prompt(
            db_session,
            task=task,
            request=request,
            claude_session=claude_session,
            repos_path=repos_path,
            redis_client=redis_client,
            active_node_context=active_node_context,
        )
    else:
        await _run_freeform_prompt(
            db_session,
            task=task,
            request=request,
            claude_session=claude_session,
            redis_client=redis_client,
            active_node_context=active_node_context,
        )
    await clear_manual_stop(redis_client, task.id, request.id)

    request.status = ManualRequestStatus.DONE
    request.processed_at = datetime.now(UTC)
    await db_session.commit()


# Верхняя граница на длительность обработки ОДНОГО запроса очереди — с
# запасом относительно любого разумного timeout_seconds ноды/умолчания
# свободного промта, чтобы блокировка не истекла раньше, чем реально
# закончится сама операция (раздел 17.4).
_MANUAL_QUEUE_LOCK_TTL_SECONDS = 3600


async def process_manual_queue_once(
    db_session: AsyncSession,
    *,
    task: Task,
    claude_session: ClaudeCodeSession,
    repos_path: Path,
    redis_client: Redis,
    active_node_context: ActiveNodeContext | None = None,
) -> int:
    """Обрабатывает ВСЕ `queued`-запросы FIFO по `requested_at` (раздел 7.3).

    Вызывается оркестратором (раздел 7.3: "прежде чем переходить к
    следующей ноде пайплайна") — не содержит собственного цикла ожидания
    новых запросов, это ответственность внешнего Celery-таска. Каждый
    отдельный запрос защищён распределённой блокировкой (раздел 17.5) —
    если другой процесс уже обрабатывает очередь этой задачи, обработка
    останавливается без ошибки (раздел 17.4: идемпотентность).
    """
    processed = 0
    stop_guard = StopGuard(redis_client=redis_client, task_id=task.id)
    while True:
        # «Остановить» задачу (раздел 14.2) — оставшиеся запросы ждут
        # перезапуска в `queued`, а не начинаются, чтобы тут же прерваться.
        if await stop_guard.is_stop_requested():
            logger.info("manual_queue_processing_stopped", task_id=str(task.id))
            return processed
        stmt = (
            sa.select(TaskManualRequestQueue)
            .where(
                TaskManualRequestQueue.task_id == task.id,
                TaskManualRequestQueue.status == ManualRequestStatus.QUEUED,
            )
            .order_by(TaskManualRequestQueue.requested_at)
            .limit(1)
        )
        request = await db_session.scalar(stmt)
        if request is None:
            return processed
        try:
            async with acquire_task_operation_lock(
                redis_client,
                task_id=task.id,
                operation=MANUAL_QUEUE_LOCK_OPERATION,
                ttl_seconds=_MANUAL_QUEUE_LOCK_TTL_SECONDS,
            ):
                await _process_single_request(
                    db_session,
                    task=task,
                    request=request,
                    claude_session=claude_session,
                    repos_path=repos_path,
                    redis_client=redis_client,
                    active_node_context=active_node_context,
                )
        except LockNotAcquiredError:
            logger.info("manual_queue_processing_already_in_progress", task_id=str(task.id))
            return processed
        processed += 1


async def expire_stale_manual_queue_requests(
    db_session: AsyncSession,
    *,
    older_than: datetime,
) -> list[uuid.UUID]:
    """Раздел 16.2: `expire_stale_manual_queue_requests`.

    Отменяет запросы, зависшие в `queued` дольше разумного порога —
    ``older_than`` уже вычислен вызывающим кодом (периодической задачей,
    её Celery-обёртка) как "сейчас минус порог". Уведомление пользователя
    (раздел 16.2: "с уведомлением пользователя", раздел 18.2) —
    отправляется здесь же, автору задачи каждого отменённого запроса.
    """
    stmt = sa.select(TaskManualRequestQueue).where(
        TaskManualRequestQueue.status == ManualRequestStatus.QUEUED,
        TaskManualRequestQueue.requested_at < older_than,
    )
    stale_requests = list((await db_session.execute(stmt)).scalars().all())
    expired_ids: list[uuid.UUID] = []
    for request in stale_requests:
        request.status = ManualRequestStatus.CANCELLED
        request.processed_at = datetime.now(UTC)
        expired_ids.append(request.id)
        logger.info(
            "manual_queue_request_expired",
            request_id=str(request.id),
            task_id=str(request.task_id),
        )
    if expired_ids:
        await db_session.commit()
        for request in stale_requests:
            task = await db_session.get(Task, request.task_id)
            if task is not None:
                await notify_task_event(
                    db_session,
                    event=NotificationEvent.MANUAL_QUEUE_REQUEST_EXPIRED,
                    task=task,
                    detail=f"{task.code}: запрос из очереди отменён по таймауту ожидания",
                )
    return expired_ids
