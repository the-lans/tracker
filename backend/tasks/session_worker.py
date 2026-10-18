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
from services.mcp_config import build_mcp_server_config
from services.pipeline_orchestrator import run_pipeline
from services.plan_mode import ActiveNodeContext, build_can_use_tool_callback
from services.session_lifecycle import plan_session_start
from services.task_status import transition_task_status
from tasks.celery_app import celery_app

if TYPE_CHECKING:
    from claude_agent_sdk.types import McpServerConfig
    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger("tasks.session_worker")

_REPOS_ROOT_ENV_VAR = "TRACKER_REPOS_ROOT"


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
def run_task_session(task_id: str) -> None:
    asyncio.run(_run_task_session_async(uuid.UUID(task_id)))


async def _run_task_session_async(task_id: uuid.UUID) -> None:
    async with async_session_factory() as db_session:
        task = await db_session.get(Task, task_id)
        if task is None:
            logger.warning("task_not_found", task_id=str(task_id))
            return

        await transition_task_status(
            db_session,
            task_id=task_id,
            from_status=TaskStatus.QUEUED,
            to_status=TaskStatus.IN_PROGRESS,
        )
        await db_session.refresh(task)

        llm_account_id = task.llm_account_id
        claude_config_dir = None
        if llm_account_id is not None:
            llm_account = await db_session.get(LlmAccount, llm_account_id)
            claude_config_dir = llm_account.claude_config_dir if llm_account else None

        repos_root = Path(os.environ.get(_REPOS_ROOT_ENV_VAR, "tracker/repos"))
        repos_path = repos_root / task.code
        mcp_servers = await _resolve_mcp_servers_for_task(db_session, task)

        active_node_context = ActiveNodeContext()
        redis_client = Redis.from_url(os.environ["REDIS_URL"])
        try:
            can_use_tool = build_can_use_tool_callback(
                context=active_node_context,
                session_factory=async_session_factory,
                redis_client=redis_client,
            )

            start_plan = plan_session_start(existing_session_id=task.session_id)
            options = build_claude_agent_options(
                resume_session_id=start_plan.resume_session_id,
                cwd=str(repos_path),
                permission_mode=task.current_permission_mode,
                mcp_servers=mcp_servers,
                claude_config_dir=claude_config_dir or "",
                enable_remote_control=start_plan.enable_remote_control,
                can_use_tool=can_use_tool,
            )
            session = ClaudeCodeSession(ClaudeSDKClient(options=options))
            await session.connect()

            start_after_order_index = task.last_failed_order_index
            outcome = await run_pipeline(
                db_session,
                task=task,
                claude_session=session,
                repos_path=repos_path,
                start_after_order_index=start_after_order_index,
                active_node_context=active_node_context,
            )
            await session.disconnect()

            if outcome.context_cleared_at_order_index is not None:
                # Раздел 11.5: сессия обрублена clear_context — следующий
                # запуск (новый run_task_session) начнёт со свежей сессией
                # с этой точки, а не продолжит здесь же (простая, надёжная
                # модель повторного постановки в очередь вместо рекурсии
                # внутри одного Celery-таска).
                task.session_id = None
                await db_session.commit()
                run_task_session.apply_async(args=[str(task_id)], countdown=1)
                return

            if outcome.completed:
                await transition_task_status(
                    db_session,
                    task_id=task_id,
                    from_status=TaskStatus.IN_PROGRESS,
                    to_status=TaskStatus.DONE,
                )
            elif outcome.failed_order_index is not None:
                await transition_task_status(
                    db_session,
                    task_id=task_id,
                    from_status=TaskStatus.IN_PROGRESS,
                    to_status=TaskStatus.FAILED,
                    failed_order_index=outcome.failed_order_index,
                )
        finally:
            await redis_client.aclose()
