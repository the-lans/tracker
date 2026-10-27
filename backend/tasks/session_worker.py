"""Celery-задача, владеющая `ClaudeSDKClient` на весь активный жизненный
цикл сессии задачи (раздел 6.1; архитектурное решение А плана реализации:
"один долгоживущий Celery-таск на сессию, не цепочка").

Это единственная точка входа, реально запускающая пайплайн задачи —
`services/pipeline_orchestrator.py` сам по себе не содержит цикла Celery,
только логику одного прогона по `task_nodes`.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import sqlalchemy as sa
from claude_agent_sdk import ClaudeSDKClient, ClaudeSDKError, RateLimitInfo
from redis.asyncio import Redis

from app_logging.config import bind_task_context, get_logger
from clients.claude_agent import (
    ClaudeAgentClientProtocol,
    ClaudeCodeSession,
    OfflineAgentClient,
    RateLimitHandler,
    build_claude_agent_options,
)
from db.models.enums import ParentSummaryStatus, RemoteControlStatus, TaskStatus
from db.models.llm import LlmAccount
from db.models.mcp import McpServer
from db.models.repositories import Repository, TemplateMcpServer
from db.models.tasks import Task, TaskParentSummary, TaskRepository
from db.session import async_session_factory
from services.child_rebase import apply_requested_rebases
from services.claude_config import ensure_history_retention, history_retention_days
from services.errors import ConflictError
from services.llm_accounts import record_rate_limit
from services.manual_queue import DEFAULT_FREEFORM_TIMEOUT_SECONDS, process_manual_queue_once
from services.mcp_config import build_mcp_server_config
from services.output_stream import build_output_publisher
from services.parent_summary import (
    REASON_NO_SESSION,
    REASON_SUMMARY_FAILED,
    deliver_parent_summary,
    deny_all_tools,
    get_or_request_parent_summary,
    mark_parent_summary_unavailable,
    needs_parent_summary,
    summarize_parent_in_fork,
    wait_for_parent_summary,
)
from services.pipeline_orchestrator import (
    CheckpointDecision,
    PipelineRunOutcome,
    StopGuard,
    run_pipeline,
)
from services.plan_mode import ActiveNodeContext, build_can_use_tool_callback
from services.rebase_resolution import has_unresolved_rebase_conflict, resolve_rebase_conflict
from services.redis_connection import redis_connection
from services.remote_control import record_bridge_status
from services.session_container import SESSION_CLI_PATH, build_session_cli_env
from services.session_heartbeat import (
    SESSION_OWNER_WAIT_SECONDS,
    SessionAlreadyOwnedError,
    keep_session_heartbeat,
)
from services.session_lifecycle import plan_session_start
from services.task_artifacts import task_artifacts_dir
from services.task_control import (
    TaskControlCommand,
    clear_task_control,
    consume_bridge_reconnect,
    consume_task_control,
    read_task_control,
)
from services.task_signal import wait_for_task_signal
from services.task_status import (
    fail_task_after_error,
    fail_task_from_current_status,
    first_unfinished_order_index,
    transition_task_status,
)
from services.task_workspace import (
    prepare_task_workspace,
    push_task_workspace,
    resolve_repos_root,
    task_root,
)
from tasks.async_runner import run_with_fresh_pool
from tasks.celery_app import celery_app

if TYPE_CHECKING:
    from claude_agent_sdk.types import CanUseTool, McpServerConfig
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
    run_with_fresh_pool(
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
    # Новый процесс CLI, продолжающий сессию с данным `session_id` с флагом
    # `--remote-control` (раздел 6.5).
    bridge_client_factory: Callable[[str], ClaudeAgentClientProtocol]
    # Новый процесс CLI с прежними флагами — после падения процесса посреди
    # ноды (раздел 17.3: временный сбой повторяется в той же сессии).
    recovery_client_factory: Callable[[str], ClaudeAgentClientProtocol]
    # Раздел 3.1: без LLM-аккаунта процесса Claude Code нет вовсе.
    has_llm: bool = True

    async def recover_session(self) -> None:
        session_id = self.claude_session.session_id or self.task.session_id
        if session_id is None:
            message = "Процесс CLI упал до первого ответа — продолжать нечего"
            raise RuntimeError(message)
        await self.claude_session.replace_client(self.recovery_client_factory(session_id))

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

        Сначала — ребейзы, запрошенные после слияния ветки родителя
        (`services/child_rebase.py`): они могут и создать конфликт. Конфликт
        узнаётся и по статусу, и по признаку в `task_repositories`: после
        неудачной автообработки и перезапуска из `failed` статус уже
        `in_progress`, а ветка всё ещё не перебазирована.
        """
        await self.db_session.refresh(self.task)
        await apply_requested_rebases(self.db_session, task=self.task, workspace=self.workspace)
        await self.db_session.refresh(self.task)
        in_conflict_status = self.task.status is TaskStatus.REBASE_CONFLICT
        if not in_conflict_status and not await has_unresolved_rebase_conflict(
            self.db_session,
            self.task,
        ):
            return True
        if not self.has_llm:
            # Конфликт разбирает агент (раздел 14) — без LLM-аккаунта некому.
            logger.info("rebase_conflict_without_llm", task_id=str(self.task.id))
            return False
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

    async def reconnect_bridge_if_requested(self) -> None:
        """
        Раздел 6.5 «Переподключить удалённую сессию» — новая попытка поднять
        мост: процесс CLI пересоздаётся с `--remote-control`, продолжая ту же
        сессию. Только между ходами — идущий ход не прерывается. Восстановление
        моста не гарантировано (решение №1 плана): статус лишь best-effort.
        """
        if not await consume_bridge_reconnect(self.redis_client, self.task.id):
            return
        await self.db_session.refresh(self.task)
        session_id = self.claude_session.session_id or self.task.session_id
        status = RemoteControlStatus.DISCONNECTED
        if session_id is None or not self.has_llm:
            logger.info("bridge_reconnect_skipped_no_session", task_id=str(self.task.id))
        else:
            try:
                await self.claude_session.replace_client(self.bridge_client_factory(session_id))
                status = RemoteControlStatus.CONNECTED
            except ClaudeSDKError:
                logger.exception("bridge_reconnect_failed", task_id=str(self.task.id))
        await record_bridge_status(self.db_session, task=self.task, status=status)

    async def _serve_between_nodes(self, *, status: TaskStatus) -> TaskControlCommand | None:
        """
        Работа между нодами (правило 16): мост, ребейз, ручные запросы — и
        команда управления после них. Неразобранный конфликт ребейза
        равносилен `stop`.
        """
        await self.reconnect_bridge_if_requested()
        if not await self.resolve_rebase_conflict_if_any(resume_status=status):
            return TaskControlCommand.STOP
        await self.process_manual_queue()
        return await read_task_control(self.redis_client, self.task.id)

    async def checkpoint(self, _order_index: int) -> CheckpointDecision:
        command = await self._serve_between_nodes(status=TaskStatus.IN_PROGRESS)
        if command is TaskControlCommand.STOP:
            return CheckpointDecision.STOP
        if command is TaskControlCommand.PAUSE and await consume_task_control(
            self.redis_client,
            self.task.id,
            TaskControlCommand.PAUSE,
        ):
            return await self._stay_paused()
        return CheckpointDecision.CONTINUE

    async def pause_after_node(self) -> CheckpointDecision:
        """
        Раздел 13.1: отметка «пауза после» — та же пауза, что по кнопке.
        Нажатая заодно кнопка «Приостановить» второй паузы не даёт: «Продолжить»
        заменяет её команду в том же ключе.
        """
        command = await self._serve_between_nodes(status=TaskStatus.IN_PROGRESS)
        if command is TaskControlCommand.STOP:
            return CheckpointDecision.STOP
        logger.info("task_paused_after_node", task_id=str(self.task.id))
        return await self._stay_paused()

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
            command = await self._serve_between_nodes(status=TaskStatus.PAUSED)
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
    котором задача сейчас (раздел 14.1)."""
    await fail_task_from_current_status(
        db_session,
        task_id=task.id,
        failed_order_index=failed_order_index,
    )
    await db_session.refresh(task)


async def _settle_bridge_request(
    db_session: AsyncSession,
    *,
    task_id: uuid.UUID,
    redis_client: Redis,
) -> None:
    """
    Раздел 6.5: «Переподключить», нажатое во время последней ноды, воркер
    выполнить уже не успеет — точки между нодами больше не будет.

    Запрос снимается, а статус `reconnecting` не остаётся навсегда: процесса
    сессии после прогона нет, мост закрыт.
    """
    requested = await consume_bridge_reconnect(redis_client, task_id)
    task = await db_session.get(Task, task_id, populate_existing=True)
    if task is None:
        return
    if requested or task.remote_control_status is RemoteControlStatus.RECONNECTING:
        logger.info("bridge_reconnect_dropped_after_run", task_id=str(task_id))
        await record_bridge_status(db_session, task=task, status=RemoteControlStatus.DISCONNECTED)


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
    with bind_task_context(task_id):
        await _run_task_session_in_context(
            task_id,
            start_after_order_index=start_after_order_index,
            continuation=continuation,
        )


async def _run_task_session_in_context(
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
        async with redis_connection() as redis_client:
            try:
                # Раздел 17.4: сначала владение сессией, затем статус — второй
                # исполнитель той же задачи уходит, ничего не изменив.
                async with keep_session_heartbeat(
                    redis_client,
                    task_id,
                    acquire_timeout=SESSION_OWNER_WAIT_SECONDS,
                ):
                    if not await _claim_task(db_session, task, continuation=continuation):
                        return
                    await _run_owned_session(
                        db_session,
                        task=task,
                        redis_client=redis_client,
                        start_after_order_index=start_after_order_index,
                        continuation=continuation,
                    )
            except SessionAlreadyOwnedError:
                logger.info("task_session_already_owned", task_id=str(task_id))


async def _run_owned_session(
    db_session: AsyncSession,
    *,
    task: Task,
    redis_client: Redis,
    start_after_order_index: int | None,
    continuation: bool,
) -> None:
    try:
        if not continuation:
            # Команда, адресованная прошлому прогону, к этому не относится.
            await clear_task_control(redis_client, task.id)
        await _run_claimed_task(
            db_session,
            task=task,
            redis_client=redis_client,
            start_after_order_index=start_after_order_index,
        )
    except Exception as exc:
        # Раздел 17.3: любая ошибка сессии переводит задачу в `failed`,
        # а не оставляет её в `in_progress` навсегда.
        logger.exception("task_session_failed", task_id=str(task.id))
        await fail_task_after_error(db_session, task_id=task.id, error=exc)
    finally:
        await _settle_bridge_request(db_session, task_id=task.id, redis_client=redis_client)


async def _claude_config_dir(db_session: AsyncSession, task: Task) -> str:
    """Раздел 19.5: изолированная конфигурация LLM-аккаунта задачи."""
    if task.llm_account_id is None:
        return ""
    llm_account = await db_session.get(LlmAccount, task.llm_account_id)
    return llm_account.claude_config_dir if llm_account else ""


def _rate_limit_recorder(db_session: AsyncSession, task: Task) -> RateLimitHandler | None:
    """Раздел 16.2: события лимитов из потока сессии обновляют статус аккаунта задачи."""
    account_id = task.llm_account_id
    if account_id is None:
        return None

    async def record(info: RateLimitInfo) -> None:
        await record_rate_limit(db_session, account_id=account_id, info=info)

    return record


async def _summarize_parent_in_fork(
    db_session: AsyncSession,
    *,
    summary: TaskParentSummary,
    child: Task,
    parent: Task,
    repos_root: Path,
) -> None:
    """
    Пересказ в ответвлении сессии свободного родителя: его история не
    меняется, а процесс CLI живёт только на время одного хода.
    """
    assert parent.session_id is not None
    parent_root = task_root(repos_root, parent)
    # После очистки репозиториев родителя его папки может не быть, а resume
    # ищет историю сессии по рабочей директории.
    parent_root.mkdir(parents=True, exist_ok=True)
    parent_config_dir = await _claude_config_dir(db_session, parent)
    options = build_claude_agent_options(
        resume_session_id=parent.session_id,
        cwd=str(parent_root),
        permission_mode=None,
        mcp_servers={},
        claude_config_dir=parent_config_dir,
        enable_remote_control=False,
        can_use_tool=deny_all_tools,
        fork_session=True,
        cli_path=str(SESSION_CLI_PATH),
        # Контейнер пересказа — часть сессии дочерней задачи: метка её.
        cli_env=await build_session_cli_env(
            task_id=child.id,
            cwd=parent_root,
            claude_config_dir=parent_config_dir,
        ),
    )
    ensure_history_retention(options.env["CLAUDE_CONFIG_DIR"], days=history_retention_days())
    fork = ClaudeCodeSession(ClaudeSDKClient(options=options))
    try:
        await fork.connect()
    except ClaudeSDKError:
        logger.exception("parent_summary_fork_failed", task_id=str(child.id))
        await mark_parent_summary_unavailable(
            db_session,
            summary=summary,
            reason=REASON_SUMMARY_FAILED,
        )
        return
    try:
        await summarize_parent_in_fork(
            db_session,
            summary=summary,
            child=child,
            parent=parent,
            claude_session=fork,
            timeout_seconds=DEFAULT_FREEFORM_TIMEOUT_SECONDS,
        )
    finally:
        await _disconnect_quietly(fork)


async def _obtain_parent_summary(
    db_session: AsyncSession,
    *,
    task: Task,
    redis_client: Redis,
    repos_root: Path,
) -> TaskParentSummary | None:
    """
    Раздел 3.1 `use_parent_summary`: пересказ родителя до старта своей
    сессии; `None` — задачу остановили, пока она ждала очередь родителя.
    """
    summary = await get_or_request_parent_summary(db_session, child=task, redis_client=redis_client)
    if summary.delivered_at is not None:
        return summary

    async def stop_requested() -> bool:
        return await read_task_control(redis_client, task.id) is TaskControlCommand.STOP

    if not await wait_for_parent_summary(
        db_session,
        summary=summary,
        redis_client=redis_client,
        is_stop_requested=stop_requested,
    ):
        return None
    if summary.status is not ParentSummaryStatus.PENDING:
        return summary
    parent = await db_session.get(Task, summary.parent_task_id, populate_existing=True)
    if parent is None or parent.session_id is None:
        await mark_parent_summary_unavailable(db_session, summary=summary, reason=REASON_NO_SESSION)
        return summary
    await _summarize_parent_in_fork(
        db_session,
        summary=summary,
        child=task,
        parent=parent,
        repos_root=repos_root,
    )
    return summary


@dataclass(frozen=True, slots=True)
class _SessionClientFactory:
    """
    Клиент сессии задачи: новый процесс CLI в контейнере сессии (раздел
    19.3) — при старте, переподключении моста и восстановлении после сбоя;
    без LLM-аккаунта — офлайн-клиент (задача только из скриптов).
    """

    task: Task
    workspace: Path
    artifacts_dir: Path
    claude_config_dir: str
    mcp_servers: dict[str, McpServerConfig]
    can_use_tool: CanUseTool
    cli_env: dict[str, str]

    @property
    def has_llm(self) -> bool:
        return self.task.llm_account_id is not None

    def __call__(
        self,
        *,
        resume_session_id: str | None,
        enable_remote_control: bool,
    ) -> ClaudeAgentClientProtocol:
        if not self.has_llm:
            return OfflineAgentClient()
        options = build_claude_agent_options(
            resume_session_id=resume_session_id,
            cwd=str(self.workspace),
            permission_mode=self.task.current_permission_mode,
            mcp_servers=self.mcp_servers,
            claude_config_dir=self.claude_config_dir,
            enable_remote_control=enable_remote_control,
            can_use_tool=self.can_use_tool,
            add_dirs=[str(self.artifacts_dir)],
            cli_path=str(SESSION_CLI_PATH),
            cli_env=self.cli_env,
        )
        return ClaudeSDKClient(options=options)


async def _build_client_factory(
    db_session: AsyncSession,
    *,
    task: Task,
    workspace: Path,
    can_use_tool: CanUseTool,
) -> _SessionClientFactory:
    claude_config_dir = await _claude_config_dir(db_session, task)
    artifacts_dir = task_artifacts_dir(task.code)
    has_llm = task.llm_account_id is not None
    cli_env = (
        await build_session_cli_env(
            task_id=task.id,
            cwd=workspace,
            claude_config_dir=claude_config_dir,
            artifacts_dir=artifacts_dir,
        )
        if has_llm
        else {}
    )
    # Раздел 6.4: история сессии нужна, пока существует задача (resume, пересказ).
    ensure_history_retention(claude_config_dir, days=history_retention_days())
    return _SessionClientFactory(
        task=task,
        workspace=workspace,
        artifacts_dir=artifacts_dir,
        claude_config_dir=claude_config_dir,
        mcp_servers=await _resolve_mcp_servers_for_task(db_session, task),
        can_use_tool=can_use_tool,
        cli_env=cli_env,
    )


async def _run_claimed_task(
    db_session: AsyncSession,
    *,
    task: Task,
    redis_client: Redis,
    start_after_order_index: int | None,
) -> None:
    repos_root = resolve_repos_root()
    workspace = await prepare_task_workspace(db_session, task=task, repos_root=repos_root)

    parent_summary = None
    if needs_parent_summary(task):
        parent_summary = await _obtain_parent_summary(
            db_session,
            task=task,
            redis_client=redis_client,
            repos_root=repos_root,
        )
        if parent_summary is None:
            logger.info("task_stopped_while_waiting_parent_summary", task_id=str(task.id))
            await _fail_task(
                db_session,
                task,
                failed_order_index=await first_unfinished_order_index(db_session, task.id),
            )
            return

    active_node_context = ActiveNodeContext()
    make_client = await _build_client_factory(
        db_session,
        task=task,
        workspace=workspace,
        can_use_tool=build_can_use_tool_callback(
            context=active_node_context,
            session_factory=async_session_factory,
            redis_client=redis_client,
        ),
    )
    start_plan = plan_session_start(existing_session_id=task.session_id)
    enable_remote_control = start_plan.enable_remote_control and make_client.has_llm
    session = ClaudeCodeSession(
        make_client(
            resume_session_id=start_plan.resume_session_id,
            enable_remote_control=enable_remote_control,
        ),
        on_text_delta=build_output_publisher(redis_client, active_node_context),
        on_abort=active_node_context.cancel_decision_wait,
        on_rate_limit=_rate_limit_recorder(db_session, task),
    )
    control = _SessionControl(
        db_session=db_session,
        task=task,
        claude_session=session,
        workspace=workspace,
        redis_client=redis_client,
        active_node_context=active_node_context,
        bridge_client_factory=lambda session_id: make_client(
            resume_session_id=session_id,
            enable_remote_control=True,
        ),
        recovery_client_factory=lambda session_id: make_client(
            resume_session_id=session_id,
            enable_remote_control=enable_remote_control,
        ),
        has_llm=make_client.has_llm,
    )
    await session.connect()
    if enable_remote_control:
        await record_bridge_status(db_session, task=task, status=RemoteControlStatus.CONNECTED)
    try:
        outcome, rebase_resolved = await _run_connected_session(
            db_session,
            control=control,
            parent_summary=parent_summary,
            start_after_order_index=start_after_order_index,
        )
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
    await _settle_pipeline_run(
        db_session,
        task=task,
        outcome=outcome,
        rebase_resolved=rebase_resolved,
        repos_root=repos_root,
        redis_client=redis_client,
    )


async def _run_connected_session(
    db_session: AsyncSession,
    *,
    control: _SessionControl,
    parent_summary: TaskParentSummary | None,
    start_after_order_index: int | None,
) -> tuple[PipelineRunOutcome | None, bool]:
    """
    Пересказ родителя, прогон пайплайна и работа после последней ноды;
    ``None`` вместо итога прогона — пайплайн не начался из-за конфликта
    ребейза. Второй элемент — конфликт ребейза разобран.
    """
    task = control.task
    session = control.claude_session
    if parent_summary is not None and parent_summary.delivered_at is None:
        await deliver_parent_summary(
            db_session,
            child=task,
            summary=parent_summary,
            claude_session=session,
            timeout_seconds=DEFAULT_FREEFORM_TIMEOUT_SECONDS,
            active_node_context=control.active_node_context,
        )
    # Конфликт, оставшийся от прошлого прогона (перезапуск из `failed`,
    # продолжение после `clear_context`), — до первой же ноды.
    if not await control.resolve_rebase_conflict_if_any(resume_status=TaskStatus.IN_PROGRESS):
        return None, False
    outcome = await run_pipeline(
        db_session,
        task=task,
        claude_session=session,
        repos_path=control.workspace,
        start_after_order_index=start_after_order_index,
        active_node_context=control.active_node_context,
        checkpoint=control.checkpoint,
        pause_after_node=control.pause_after_node,
        stop_guard=StopGuard(redis_client=control.redis_client, task_id=task.id),
        recover_session=control.recover_session,
    )
    if not outcome.completed:
        return outcome, True
    # Пайплайн пройден, но сессия ещё жива: конфликт ребейза и запросы,
    # поставленные во время последней ноды, — до пуша. Пауза/остановка после
    # последней ноды уже ни к чему не относятся.
    await clear_task_control(control.redis_client, task.id)
    rebase_resolved = await control.resolve_rebase_conflict_if_any(
        resume_status=TaskStatus.IN_PROGRESS,
    )
    if rebase_resolved:
        await control.process_manual_queue()
    return outcome, rebase_resolved


async def _settle_pipeline_run(
    db_session: AsyncSession,
    *,
    task: Task,
    outcome: PipelineRunOutcome | None,
    rebase_resolved: bool,
    repos_root: Path,
    redis_client: Redis,
) -> None:
    """Итог прогона: пуш и `done`, либо `failed` с нодой, откуда продолжить."""
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
