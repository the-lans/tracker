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
from services.mcp_config import build_mcp_server_config
from services.pipeline_orchestrator import run_pipeline
from services.plan_mode import ActiveNodeContext, build_can_use_tool_callback
from services.session_lifecycle import plan_session_start
from services.task_status import fail_task_after_error, transition_task_status
from services.task_workspace import prepare_task_workspace, push_task_workspace
from tasks.celery_app import celery_app

if TYPE_CHECKING:
    from claude_agent_sdk.types import McpServerConfig
    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger("tasks.session_worker")

_REPOS_ROOT_ENV_VAR = "TRACKER_REPOS_ROOT"
_DEFAULT_REPOS_ROOT = "tracker/repos"
_CONTINUATION_COUNTDOWN_SECONDS = 1
# `failed` — «Перезапустить с текущей ноды» (раздел 14.2).
_CLAIMABLE_STATUSES = (TaskStatus.QUEUED, TaskStatus.FAILED)


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
        return task.status is TaskStatus.IN_PROGRESS
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

    repos_root = Path(os.environ.get(_REPOS_ROOT_ENV_VAR, _DEFAULT_REPOS_ROOT))
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
    session = ClaudeCodeSession(ClaudeSDKClient(options=options))
    await session.connect()
    try:
        outcome = await run_pipeline(
            db_session,
            task=task,
            claude_session=session,
            repos_path=workspace,
            start_after_order_index=start_after_order_index,
            active_node_context=active_node_context,
        )
    except BaseException:
        await _disconnect_quietly(session)
        raise

    if outcome.context_cleared_at_order_index is not None:
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

    if outcome.completed:
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
        await transition_task_status(
            db_session,
            task_id=task.id,
            from_status=TaskStatus.IN_PROGRESS,
            to_status=TaskStatus.FAILED,
            failed_order_index=outcome.failed_order_index,
        )
