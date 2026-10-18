"""Celery-задачи периодического обслуживания (раздел 16 ТЗ).

Каждая обёрнута `_run_periodic`: одна `AsyncSession` на запуск (правило C
плана реализации), исключение не роняет процесс Celery Beat/worker
(раздел 16.3) — перехватывается, пишется в `app_logs`, `last_run_status`
фиксируется как `failed`; в любом случае `last_run_at`/`next_run_at`
обновляются через `services.periodic_tasks.record_periodic_task_run`.

Celery-задачи — синхронные функции (`@celery_app.task`); внутри каждая
через `asyncio.run` вызывает асинхронное тело, использующее `services/`.
"""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
import sqlalchemy as sa

from app_logging.config import get_logger
from clients.gitlab import GitlabClient
from db.models.enums import (
    AppLogLevel,
    MergeStatus,
    PeriodicRunStatus,
    RemoteControlStatus,
    RepositoryRole,
)
from db.models.logs import AppLog
from db.models.periodic import PeriodicTask
from db.models.repositories import Repository
from db.models.tasks import TaskRepository
from db.session import async_session_factory
from services import gitlab_sync, maintenance_tasks
from services.autostart import run_scheduled_autostart_check
from services.manual_queue import expire_stale_manual_queue_requests
from services.notifications import NotificationEvent, notify_task_event
from services.periodic_tasks import record_periodic_task_run
from services.remote_control import decide_remote_control_bridge_action
from services.template_context import resolve_global_env_value
from tasks.celery_app import celery_app

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger("tasks.periodic")

_REPOS_ROOT_ENV_VAR = "TRACKER_REPOS_ROOT"
_GITLAB_URL_ENV_KEY = "GITLAB_URL"
_GITLAB_TOKEN_ENV_KEY = "GITLAB_TOKEN"


async def _get_periodic_task(db_session: AsyncSession, name: str) -> PeriodicTask | None:
    stmt = sa.select(PeriodicTask).where(PeriodicTask.name == name)
    result: PeriodicTask | None = await db_session.scalar(stmt)
    return result


async def _run_periodic_async(name: str, body: Callable[[AsyncSession], Awaitable[None]]) -> None:
    async with async_session_factory() as db_session:
        periodic_task = await _get_periodic_task(db_session, name)
        if periodic_task is None:
            logger.warning("periodic_task_not_seeded", name=name)
            return

        ran_at = datetime.now(UTC)
        status = PeriodicRunStatus.SUCCESS
        try:
            await body(db_session)
        except Exception as exc:  # noqa: BLE001 — раздел 16.3: любая ошибка периодической задачи логируется, не роняет процесс
            status = PeriodicRunStatus.FAILED
            logger.error("periodic_task_failed", name=name, error=str(exc))
            db_session.add(
                AppLog(
                    level=AppLogLevel.ERROR,
                    source=f"periodic.{name}",
                    message=str(exc),
                    context={},
                ),
            )
            await db_session.commit()
        await record_periodic_task_run(
            db_session,
            periodic_task=periodic_task,
            status=status,
            ran_at=ran_at,
        )


def _run_periodic(name: str, body: Callable[[AsyncSession], Awaitable[None]]) -> None:
    asyncio.run(_run_periodic_async(name, body))


@celery_app.task(name="check_scheduled_tasks_for_autostart")
def check_scheduled_tasks_for_autostart() -> None:
    async def body(db_session: AsyncSession) -> None:
        await run_scheduled_autostart_check(db_session, now=datetime.now(UTC))

    _run_periodic("check_scheduled_tasks_for_autostart", body)


@celery_app.task(name="check_llm_account_limits")
def check_llm_account_limits() -> None:
    async def body(_db_session: AsyncSession) -> None:
        maintenance_tasks.check_llm_account_limits()

    _run_periodic("check_llm_account_limits", body)


@celery_app.task(name="cleanup_stale_worktrees")
def cleanup_stale_worktrees() -> None:
    async def body(db_session: AsyncSession) -> None:
        stale = await maintenance_tasks.find_tasks_needing_cleanup_reminder(
            db_session,
            now=datetime.now(UTC),
        )
        logger.info("stale_worktrees_found", count=len(stale))

    _run_periodic("cleanup_stale_worktrees", body)


@celery_app.task(name="detect_awaiting_input_timeout")
def detect_awaiting_input_timeout() -> None:
    async def body(db_session: AsyncSession) -> None:
        overdue = await maintenance_tasks.find_tasks_awaiting_input_beyond_threshold(
            db_session,
            now=datetime.now(UTC),
        )
        logger.info("awaiting_input_timeouts_found", count=len(overdue))

    _run_periodic("detect_awaiting_input_timeout", body)


async def _build_gitlab_client(db_session: AsyncSession) -> GitlabClient | None:
    base_url = await resolve_global_env_value(db_session, key=_GITLAB_URL_ENV_KEY)
    token = await resolve_global_env_value(db_session, key=_GITLAB_TOKEN_ENV_KEY)
    if base_url is None or token is None:
        logger.warning("gitlab_credentials_not_configured")
        return None
    return GitlabClient(base_url=base_url, token=token, http_client=httpx.AsyncClient())


@celery_app.task(name="sync_gitlab_merge_status")
def sync_gitlab_merge_status() -> None:
    async def body(db_session: AsyncSession) -> None:
        gitlab_client = await _build_gitlab_client(db_session)
        if gitlab_client is None:
            return
        stmt = (
            sa.select(TaskRepository, Repository)
            .join(Repository, Repository.id == TaskRepository.repository_id)
            .where(
                TaskRepository.role == RepositoryRole.READ_WRITE,
                TaskRepository.merge_status != MergeStatus.NOT_PUSHED,
                TaskRepository.merge_status != MergeStatus.MERGED,
            )
        )
        rows = (await db_session.execute(stmt)).all()
        for task_repository, repository in rows:
            await gitlab_sync.sync_task_repository_merge_status(
                db_session,
                task_repository=task_repository,
                repository=repository,
                gitlab_client=gitlab_client,
            )

    _run_periodic("sync_gitlab_merge_status", body)


@celery_app.task(name="rebase_child_branches_on_parent_merge")
def rebase_child_branches_on_parent_merge() -> None:
    async def body(db_session: AsyncSession) -> None:
        repos_root = os.environ.get(_REPOS_ROOT_ENV_VAR, "tracker/repos")
        stmt = sa.select(TaskRepository).where(TaskRepository.merge_status == MergeStatus.MERGED)
        merged = list((await db_session.execute(stmt)).scalars().all())
        for parent_task_repository in merged:
            await gitlab_sync.rebase_child_task_repositories_on_parent_merge(
                db_session,
                parent_task_repository=parent_task_repository,
                repos_root=Path(repos_root),
            )

    _run_periodic("rebase_child_branches_on_parent_merge", body)


@celery_app.task(name="purge_orphaned_docker_containers")
def purge_orphaned_docker_containers() -> None:
    async def body(_db_session: AsyncSession) -> None:
        await maintenance_tasks.purge_orphaned_docker_containers()

    _run_periodic("purge_orphaned_docker_containers", body)


@celery_app.task(name="purge_orphaned_playwright_processes")
def purge_orphaned_playwright_processes() -> None:
    async def body(_db_session: AsyncSession) -> None:
        maintenance_tasks.purge_orphaned_playwright_processes()

    _run_periodic("purge_orphaned_playwright_processes", body)


@celery_app.task(name="rotate_task_logs")
def rotate_task_logs() -> None:
    async def body(db_session: AsyncSession) -> None:
        eligible = await maintenance_tasks.find_node_logs_eligible_for_rotation(
            db_session,
            now=datetime.now(UTC),
        )
        logger.info("node_logs_eligible_for_rotation", count=len(eligible))

    _run_periodic("rotate_task_logs", body)


@celery_app.task(name="revoke_stale_sshfs_keys")
def revoke_stale_sshfs_keys() -> None:
    async def body(_db_session: AsyncSession) -> None:
        maintenance_tasks.revoke_stale_sshfs_keys()

    _run_periodic("revoke_stale_sshfs_keys", body)


@celery_app.task(name="health_check_mcp_servers")
def health_check_mcp_servers() -> None:
    async def body(db_session: AsyncSession) -> None:
        async with httpx.AsyncClient() as http_client:
            await maintenance_tasks.health_check_all_mcp_servers(
                db_session,
                http_client=http_client,
            )

    _run_periodic("health_check_mcp_servers", body)


@celery_app.task(name="deprovision_inactive_users")
def deprovision_inactive_users() -> None:
    async def body(_db_session: AsyncSession) -> None:
        maintenance_tasks.deprovision_inactive_users()

    _run_periodic("deprovision_inactive_users", body)


@celery_app.task(name="check_remote_control_bridges")
def check_remote_control_bridges() -> None:
    async def body(db_session: AsyncSession) -> None:
        tasks = await maintenance_tasks.find_tasks_requiring_remote_control_check(db_session)
        for task in tasks:
            # Раздел 6.6, решение №1 плана: "жив ли процесс" здесь определяется
            # приблизительно, без реестра активных сессий оркестратора (появится
            # вместе с ним) — заведомо считается живым, если задача не отмечена
            # disconnected дольше двух проверок подряд.
            decision = decide_remote_control_bridge_action(
                is_process_alive=True,
                current_reconnect_attempts=task.remote_control_reconnect_attempts,
            )
            if decision.new_status is not None:
                task.remote_control_status = decision.new_status
                task.remote_control_last_check_at = datetime.now(UTC)
                # Раздел 18.2: уведомление только когда восстановление НЕ
                # удалось (попытки исчерпаны) — переход в "reconnecting"
                # ещё не финальная неудача.
                if decision.new_status is RemoteControlStatus.DISCONNECTED:
                    await notify_task_event(
                        db_session,
                        event=NotificationEvent.REMOTE_CONTROL_DISCONNECTED,
                        task=task,
                    )
        await db_session.commit()

    _run_periodic("check_remote_control_bridges", body)


@celery_app.task(name="expire_stale_manual_queue_requests")
def expire_stale_manual_queue_requests_task() -> None:
    async def body(db_session: AsyncSession) -> None:
        older_than = datetime.now(UTC) - timedelta(minutes=30)
        expired = await expire_stale_manual_queue_requests(db_session, older_than=older_than)
        logger.info("manual_queue_requests_expired", count=len(expired))

    _run_periodic("expire_stale_manual_queue_requests", body)
