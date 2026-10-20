"""Celery-задача, владеющая `ClaudeSDKClient` на весь активный жизненный
цикл сессии задачи (раздел 6.1; архитектурное решение А плана реализации:
"один долгоживущий Celery-таск на сессию, не цепочка").

Это единственная точка входа, реально запускающая пайплайн задачи —
`services/pipeline_orchestrator.py` сам по себе не содержит цикла Celery,
только логику одного прогона по `task_nodes`.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import sqlalchemy as sa
from claude_agent_sdk import ClaudeSDKClient
from redis.asyncio import Redis

from app_logging.config import get_logger
from clients.claude_agent import ClaudeCodeSession, build_claude_agent_options
from db.models.enums import TaskStatus
from db.models.llm import LlmAccount
from db.models.mcp import McpServer
from db.models.repositories import Repository, TemplateMcpServer
from db.models.tasks import Task, TaskRepository
from db.session import async_session_factory
from services.errors import ConflictError
from services.manual_queue import process_manual_queue_once
from services.mcp_config import build_mcp_server_config
from services.output_stream import build_output_publisher
from services.pipeline_orchestrator import CheckpointDecision, StopGuard, run_pipeline
from services.plan_mode import ActiveNodeContext, build_can_use_tool_callback
from services.rebase_resolution import has_unresolved_rebase_conflict, resolve_rebase_conflict
from services.session_lifecycle import plan_session_start
from services.task_control import (
    TaskControlCommand,
    clear_task_control,
    consume_task_control,
    read_task_control,
)
from services.task_signal import wait_for_task_signal
from services.task_status import (
    FAILABLE_STATUSES,
    fail_task_after_error,
    first_unfinished_order_index,
    transition_task_status,
)
from services.task_workspace import (
    prepare_task_workspace,
    push_task_workspace,
    resolve_repos_root,
)
from tasks.celery_app import celery_app

if TYPE_CHECKING:
    from claude_agent_sdk.types import McpServerConfig
    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger("tasks.session_worker")

_CONTINUATION_COUNTDOWN_SECONDS = 1
# `failed` — «Перезапустить с текущей ноды» (раздел 14.2).
_CLAIMABLE_STATUSES = (TaskStatus.QUEUED, TaskStatus.FAILED)
# Продолжение после `clear_context`: пока сессия передавалась, периодическая
# задача могла поймать конфликт ребейза — его разберёт первая же точка
# проверки нового таска.
_CONTINUATION_STATUSES = (TaskStatus.IN_PROGRESS, TaskStatus.REBASE_CONFLICT)
# Пауза ждёт команды без ограничения по времени; таймаут лишь страхует от
# потерянного сигнала (опубликован до подписки).
_PAUSE_POLL_SECONDS = 30.0


async def _resolve_mcp_servers_for_task(
    db_session: AsyncSession,
    task: Task,
) -> dict[str, McpServerConfig]:
    """Раздел 10.5: MCP-серверы, доступные через шаблоны репозиториев задачи."""
    stmt = (
        sa.select(McpServer)
        .join(TemplateMcpServer, TemplateMcpServer.mcp_server_id == McpServer.id)
        .join(Repository, Repository.default_template_id == TemplateMcpServer.template_id)
        .join(TaskRepository, TaskRepository.repository_id == Repository.id)
        .where(TaskRepository.task_id == task.id)
        .distinct()
    )
    servers = (await db_session.execute(stmt)).scalars().all()
    return {server.name: build_mcp_server_config(server, task=task) for server in servers}


@celery_app.task(name="run_task_session")
def run_task_session(
    task_id: str,
    start_after_order_index: int | None = None,
    continuation: bool = False,
) -> None:
    """``start_after_order_index`` — ноды с ``order_index`` не больше него
    не выполняются (продолжение после `clear_context`, перезапуск после
    `failed`). ``continuation`` — задача уже в `in_progress`: предыдущий
    таск передал сессию этому после `clear_context` (раздел 11.5)."""
    asyncio.run(
        _run_task_session_async(
            uuid.UUID(task_id),
            start_after_order_index=start_after_order_index,
            continuation=continuation,
        ),
    )


async def _claim_task(db_session: AsyncSession, task: Task, *, continuation: bool) -> bool:
    """Переводит задачу в `in_progress`; False — задачу уже взял другой таск.

    Compare-and-swap (раздел 17.4) делает повторную доставку Celery-задачи
    и двойной клик «Перезапустить» безопасными: второй таск проигрывает
    переход и завершается без побочных эффектов (раздел 17.4, идемпотентность).
    """
    if continuation:
        return task.status in _CONTINUATION_STATUSES
    if task.status not in _CLAIMABLE_STATUSES:
        logger.info("task_not_claimable", task_id=str(task.id), status=task.status)
        return False
    try:
        await transition_task_status(
            db_session,
            task_id=task.id,
            from_status=task.status,
            to_status=TaskStatus.IN_PROGRESS,
        )
    except ConflictError:
        logger.info("task_already_claimed", task_id=str(task.id))
        return False
    await db_session.refresh(task)
    return True


@dataclass(slots=True)
class _SessionControl:
    """Всё, что воркер делает между нодами, пока владеет сессией.

    Порядок в точке проверки (`checkpoint`): конфликт ребейза (раздел 14),
    затем очередь ручных запросов FIFO (раздел 7.3 — «прежде, чем
    переходить к следующей ноде»), затем команды пользователя (раздел 14.2).
    """

    db_session: AsyncSession
    task: Task
    claude_session: ClaudeCodeSession
    workspace: Path
    redis_client: Redis
    active_node_context: ActiveNodeContext

    async def process_manual_queue(self) -> None:
        await process_manual_queue_once(
            self.db_session,
            task=self.task,
            claude_session=self.claude_session,
            repos_path=self.workspace,
            redis_client=self.redis_client,
            active_node_context=self.active_node_context,
        )

    async def resolve_rebase_conflict_if_any(self, *, resume_status: TaskStatus) -> bool:
        """
        `False` — агент не справился, задачу надо переводить в `failed`.

        Конфликт узнаётся и по статусу, и по признаку в `task_repositories`:
        после неудачной автообработки и перезапуска из `failed` статус уже
        `in_progress`, а ветка всё ещё не перебазирована.
        """
        await self.db_session.refresh(self.task)
        in_conflict_status = self.task.status is TaskStatus.REBASE_CONFLICT
        if not in_conflict_status and not await has_unresolved_rebase_conflict(
            self.db_session,
            self.task,
        ):
            return True
        logger.info("rebase_conflict_resolution_started", task_id=str(self.task.id))
        if not await resolve_rebase_conflict(
            self.db_session,
            task=self.task,
            claude_session=self.claude_session,
            workspace=self.workspace,
            active_node_context=self.active_node_context,
        ):
            return False
        if not in_conflict_status:
            return True
        await transition_task_status(
            self.db_session,
            task_id=self.task.id,
            from_status=TaskStatus.REBASE_CONFLICT,
            to_status=TaskStatus.IN_PROGRESS,
        )
        if resume_status is TaskStatus.PAUSED:
            await transition_task_status(
                self.db_session,
                task_id=self.task.id,
                from_status=TaskStatus.IN_PROGRESS,
                to_status=TaskStatus.PAUSED,
            )
        await self.db_session.refresh(self.task)
        return True

    async def checkpoint(self, _order_index: int) -> CheckpointDecision:
        if not await self.resolve_rebase_conflict_if_any(resume_status=TaskStatus.IN_PROGRESS):
            return CheckpointDecision.STOP
        await self.process_manual_queue()
        command = await read_task_control(self.redis_client, self.task.id)
        if command is TaskControlCommand.STOP:
            return CheckpointDecision.STOP
        if command is TaskControlCommand.PAUSE and await consume_task_control(
            self.redis_client,
            self.task.id,
            TaskControlCommand.PAUSE,
        ):
            return await self._stay_paused()
        return CheckpointDecision.CONTINUE

    async def _stay_paused(self) -> CheckpointDecision:
        """
        Раздел 14.2 «Приостановить»: сессия удерживается, ручные запросы
        выполняются, пайплайн ждёт «Продолжить» или «Остановить».

        Периодическая задача может параллельно перевести задачу в
        `rebase_conflict` — тогда compare-and-swap перехода проигрывает, и
        цикл сначала разбирает конфликт, а затем повторяет переход.
        """
        while not await self._try_transition(TaskStatus.IN_PROGRESS, TaskStatus.PAUSED):
            if not await self.resolve_rebase_conflict_if_any(resume_status=TaskStatus.IN_PROGRESS):
                return CheckpointDecision.STOP
        logger.info("task_paused", task_id=str(self.task.id))
        while True:
            if not await self.resolve_rebase_conflict_if_any(resume_status=TaskStatus.PAUSED):
                return CheckpointDecision.STOP
            await self.process_manual_queue()
            command = await read_task_control(self.redis_client, self.task.id)
            if command is TaskControlCommand.STOP:
                return CheckpointDecision.STOP
            if command is TaskControlCommand.RESUME:
                # Команда забирается только после перехода: проигранный
                # переход не должен терять «Продолжить».
                if not await self._try_transition(TaskStatus.PAUSED, TaskStatus.IN_PROGRESS):
                    continue
                # Если «Продолжить» уже заменил `stop`, consume его не тронет,
                # и следующая нода остановится, не начавшись (`run_stoppable`).
                await consume_task_control(
                    self.redis_client,
                    self.task.id,
                    TaskControlCommand.RESUME,
                )
                logger.info("task_resumed", task_id=str(self.task.id))
                return CheckpointDecision.CONTINUE
            await wait_for_task_signal(self.redis_client, self.task.id, timeout=_PAUSE_POLL_SECONDS)

    async def _try_transition(self, from_status: TaskStatus, to_status: TaskStatus) -> bool:
        try:
            await transition_task_status(
                self.db_session,
                task_id=self.task.id,
                from_status=from_status,
                to_status=to_status,
            )
        except ConflictError:
            logger.info(
                "task_status_changed_concurrently",
                task_id=str(self.task.id),
                expected_status=from_status,
            )
            return False
        await self.db_session.refresh(self.task)
        return True


async def _fail_task(db_session: AsyncSession, task: Task, *, failed_order_index: int) -> None:
    """Сбой, остановка или неразрешённый конфликт — из того статуса, в
    котором задача сейчас: пока шла нода, её могли поставить на паузу или
    поймать конфликт ребейза (раздел 14.1)."""
    await db_session.refresh(task)
    if task.status not in FAILABLE_STATUSES:
        logger.warning(
            "task_not_failed_unexpected_status",
            task_id=str(task.id),
            status=task.status,
        )
        return
    await transition_task_status(
        db_session,
        task_id=task.id,
        from_status=task.status,
        to_status=TaskStatus.FAILED,
        failed_order_index=failed_order_index,
    )


async def _disconnect_quietly(session: ClaudeCodeSession) -> None:
    try:
        await session.disconnect()
    except Exception:  # noqa: BLE001 — уже обрабатываем исходную ошибку, эта вторична
        logger.exception("session_disconnect_failed")


async def _run_task_session_async(
    task_id: uuid.UUID,
    *,
    start_after_order_index: int | None,
    continuation: bool,
) -> None:
    async with async_session_factory() as db_session:
        task = await db_session.get(Task, task_id)
        if task is None:
            logger.warning("task_not_found", task_id=str(task_id))
            return
        if not await _claim_task(db_session, task, continuation=continuation):
            return

        redis_client = Redis.from_url(os.environ["REDIS_URL"])
        try:
            if not continuation:
                # Команда, адресованная прошлому прогону, к этому не относится.
                await clear_task_control(redis_client, task_id)
            await _run_claimed_task(
                db_session,
                task=task,
                redis_client=redis_client,
                start_after_order_index=start_after_order_index,
            )
        except Exception as exc:
            # Раздел 17.3: любая ошибка сессии переводит задачу в `failed`,
            # а не оставляет её в `in_progress` навсегда.
            logger.exception("task_session_failed", task_id=str(task_id))
            await fail_task_after_error(db_session, task_id=task_id, error=exc)
        finally:
            await redis_client.aclose()


async def _run_claimed_task(
    db_session: AsyncSession,
    *,
    task: Task,
    redis_client: Redis,
    start_after_order_index: int | None,
) -> None:
    claude_config_dir = None
    if task.llm_account_id is not None:
        llm_account = await db_session.get(LlmAccount, task.llm_account_id)
        claude_config_dir = llm_account.claude_config_dir if llm_account else None

    repos_root = resolve_repos_root()
    workspace = await prepare_task_workspace(db_session, task=task, repos_root=repos_root)
    mcp_servers = await _resolve_mcp_servers_for_task(db_session, task)

    active_node_context = ActiveNodeContext()
    can_use_tool = build_can_use_tool_callback(
        context=active_node_context,
        session_factory=async_session_factory,
        redis_client=redis_client,
    )
    start_plan = plan_session_start(existing_session_id=task.session_id)
    options = build_claude_agent_options(
        resume_session_id=start_plan.resume_session_id,
        cwd=str(workspace),
        permission_mode=task.current_permission_mode,
        mcp_servers=mcp_servers,
        claude_config_dir=claude_config_dir or "",
        enable_remote_control=start_plan.enable_remote_control,
        can_use_tool=can_use_tool,
    )
    session = ClaudeCodeSession(
        ClaudeSDKClient(options=options),
        on_text_delta=build_output_publisher(redis_client, active_node_context),
    )
    control = _SessionControl(
        db_session=db_session,
        task=task,
        claude_session=session,
        workspace=workspace,
        redis_client=redis_client,
        active_node_context=active_node_context,
    )
    await session.connect()
    outcome = None
    try:
        # Конфликт, оставшийся от прошлого прогона (перезапуск из `failed`,
        # продолжение после `clear_context`), — до первой же ноды.
        rebase_resolved = await control.resolve_rebase_conflict_if_any(
            resume_status=TaskStatus.IN_PROGRESS,
        )
        if rebase_resolved:
            outcome = await run_pipeline(
                db_session,
                task=task,
                claude_session=session,
                repos_path=workspace,
                start_after_order_index=start_after_order_index,
                active_node_context=active_node_context,
                checkpoint=control.checkpoint,
                stop_guard=StopGuard(redis_client=redis_client, task_id=task.id),
            )
        if outcome is not None and outcome.completed:
            # Пайплайн пройден, но сессия ещё жива: конфликт ребейза и
            # запросы, поставленные во время последней ноды, — до пуша.
            # Пауза/остановка после последней ноды уже ни к чему не относятся.
            await clear_task_control(redis_client, task.id)
            rebase_resolved = await control.resolve_rebase_conflict_if_any(
                resume_status=TaskStatus.IN_PROGRESS,
            )
            if rebase_resolved:
                await control.process_manual_queue()
    except BaseException:
        await _disconnect_quietly(session)
        raise

    if outcome is not None and outcome.context_cleared_at_order_index is not None:
        # Раздел 11.5: оркестратор уже оборвал сессию. Следующий таск начнёт
        # со свежей сессией с этой точки — без повторного захвата статуса.
        run_task_session.apply_async(
            args=[str(task.id)],
            kwargs={
                "start_after_order_index": outcome.context_cleared_at_order_index,
                "continuation": True,
            },
            countdown=_CONTINUATION_COUNTDOWN_SECONDS,
        )
        return
    await session.disconnect()

    if outcome is None or (outcome.completed and not rebase_resolved):
        await _fail_task(
            db_session,
            task,
            failed_order_index=await first_unfinished_order_index(db_session, task.id),
        )
    elif outcome.completed:
        await push_task_workspace(
            db_session,
            task=task,
            repos_root=repos_root,
            redis_client=redis_client,
        )
        await transition_task_status(
            db_session,
            task_id=task.id,
            from_status=TaskStatus.IN_PROGRESS,
            to_status=TaskStatus.DONE,
        )
    elif outcome.failed_order_index is not None:
        if outcome.stopped:
            logger.info("task_stopped_by_user", task_id=str(task.id))
        await _fail_task(db_session, task, failed_order_index=outcome.failed_order_index)
