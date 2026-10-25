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

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import httpx
import sqlalchemy as sa

from app_logging.config import get_logger
from clients.gitlab import GitlabClient
from db.models.enums import (
    AppLogLevel,
    MergeStatus,
    PeriodicRunStatus,
    RepositoryRole,
)
from db.models.logs import AppLog
from db.models.periodic import PeriodicTask
from db.models.repositories import Repository
from db.models.tasks import Task, TaskRepository
from db.session import async_session_factory
from services import gitlab_sync, maintenance_tasks, users
from services.autostart import run_scheduled_autostart_check
from services.llm_accounts import restore_expired_rate_limits
from services.log_rotation import resolve_archive_root, rotate_node_logs
from services.manual_queue import STALE_QUEUED_REQUEST_AGE, expire_stale_manual_queue_requests
from services.periodic_tasks import mark_periodic_task_running, record_periodic_task_run
from services.redis_connection import redis_connection
from services.remote_control import check_session_bridges
from services.system_settings import get_gitlab_credentials
from tasks.async_runner import run_with_fresh_pool
from tasks.celery_app import celery_app
from tasks.session_worker import run_task_session

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger("tasks.periodic")


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
        await mark_periodic_task_running(db_session, periodic_task=periodic_task)
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
    run_with_fresh_pool(_run_periodic_async(name, body))


@celery_app.task(name="check_scheduled_tasks_for_autostart")
def check_scheduled_tasks_for_autostart() -> None:
    async def body(db_session: AsyncSession) -> None:
        result = await run_scheduled_autostart_check(db_session, now=datetime.now(UTC))
        # Раздел 12.2 (п. 2): «тот же процесс запуска, что и кнопка
        # «Выполнить»» — после `new -> queued` таск сессии ставится в очередь.
        for task_id in result.started_task_ids:
            run_task_session.delay(str(task_id))

    _run_periodic("check_scheduled_tasks_for_autostart", body)


@celery_app.task(name="check_llm_account_limits")
def check_llm_account_limits() -> None:
    async def body(db_session: AsyncSession) -> None:
        await restore_expired_rate_limits(db_session, now=datetime.now(UTC))

    _run_periodic("check_llm_account_limits", body)


@celery_app.task(name="cleanup_stale_worktrees")
def cleanup_stale_worktrees() -> None:
    async def body(db_session: AsyncSession) -> None:
        async with redis_connection() as redis_client:
            reminded = await maintenance_tasks.send_cleanup_reminders(
                db_session,
                redis_client=redis_client,
                now=datetime.now(UTC),
            )
        logger.info("cleanup_reminders_sent", count=len(reminded))

    _run_periodic("cleanup_stale_worktrees", body)


@celery_app.task(name="detect_awaiting_input_timeout")
def detect_awaiting_input_timeout() -> None:
    async def body(db_session: AsyncSession) -> None:
        async with redis_connection() as redis_client:
            reminded = await maintenance_tasks.send_awaiting_decision_reminders(
                db_session,
                redis_client=redis_client,
                now=datetime.now(UTC),
            )
        logger.info("awaiting_decision_reminders_sent", count=len(reminded))

    _run_periodic("detect_awaiting_input_timeout", body)


@celery_app.task(name="sync_gitlab_merge_status")
def sync_gitlab_merge_status() -> None:
    async def body(db_session: AsyncSession) -> None:
        credentials = await get_gitlab_credentials(db_session)
        if credentials is None:
            logger.warning("gitlab_credentials_not_configured")
            return
        stmt = (
            sa.select(TaskRepository, Repository, Task)
            .join(Repository, Repository.id == TaskRepository.repository_id)
            .join(Task, Task.id == TaskRepository.task_id)
            .where(
                TaskRepository.role == RepositoryRole.READ_WRITE,
                TaskRepository.merge_status != MergeStatus.NOT_PUSHED,
                TaskRepository.merge_status != MergeStatus.MERGED,
            )
        )
        rows = [
            (task_repository, repository, task)
            for task_repository, repository, task in (await db_session.execute(stmt)).all()
        ]
        async with redis_connection() as redis_client, httpx.AsyncClient() as http_client:
            await gitlab_sync.sync_merge_statuses(
                db_session,
                rows=rows,
                gitlab_client=GitlabClient(
                    base_url=credentials.url,
                    token=credentials.token,
                    http_client=http_client,
                ),
                redis_client=redis_client,
            )

    _run_periodic("sync_gitlab_merge_status", body)


@celery_app.task(name="rebase_child_branches_on_parent_merge")
def rebase_child_branches_on_parent_merge() -> None:
    async def body(db_session: AsyncSession) -> None:
        merged = await gitlab_sync.find_merged_parents_with_children(db_session)
        async with redis_connection() as redis_client:
            for parent_task_repository in merged:
                await gitlab_sync.request_child_rebases_on_parent_merge(
                    db_session,
                    parent_task_repository=parent_task_repository,
                    redis_client=redis_client,
                )

    _run_periodic("rebase_child_branches_on_parent_merge", body)


@celery_app.task(name="purge_orphaned_docker_containers")
def purge_orphaned_docker_containers() -> None:
    async def body(_db_session: AsyncSession) -> None:
        await maintenance_tasks.purge_orphaned_docker_containers()
        async with redis_connection() as redis_client:
            await maintenance_tasks.purge_orphaned_session_containers(redis_client)

    _run_periodic("purge_orphaned_docker_containers", body)


@celery_app.task(name="purge_orphaned_playwright_processes")
def purge_orphaned_playwright_processes() -> None:
    async def body(_db_session: AsyncSession) -> None:
        maintenance_tasks.purge_orphaned_playwright_processes()

    _run_periodic("purge_orphaned_playwright_processes", body)


@celery_app.task(name="rotate_task_logs")
def rotate_task_logs() -> None:
    async def body(db_session: AsyncSession) -> None:
        result = await rotate_node_logs(
            db_session,
            archive_root=resolve_archive_root(),
            now=datetime.now(UTC),
        )
        logger.info(
            "node_logs_rotated",
            files=len(result.archived_files),
            deleted=result.deleted_count,
        )

    _run_periodic("rotate_task_logs", body)


@celery_app.task(name="revoke_stale_sshfs_keys")
def revoke_stale_sshfs_keys() -> None:
    async def body(db_session: AsyncSession) -> None:
        async with redis_connection() as redis_client:
            reminded = await maintenance_tasks.revoke_stale_sshfs_keys(
                db_session,
                redis_client=redis_client,
                now=datetime.now(UTC),
            )
        logger.info("stale_ssh_key_reminders_sent", count=len(reminded))

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
    async def body(db_session: AsyncSession) -> None:
        deprovisioned = await users.deprovision_inactive_users(db_session)
        logger.info("inactive_users_deprovisioned", count=len(deprovisioned))

    _run_periodic("deprovision_inactive_users", body)


@celery_app.task(name="check_remote_control_bridges")
def check_remote_control_bridges() -> None:
    async def body(db_session: AsyncSession) -> None:
        async with redis_connection() as redis_client:
            await check_session_bridges(db_session, redis_client=redis_client)

    _run_periodic("check_remote_control_bridges", body)


@celery_app.task(name="expire_stale_manual_queue_requests")
def expire_stale_manual_queue_requests_task() -> None:
    async def body(db_session: AsyncSession) -> None:
        older_than = datetime.now(UTC) - STALE_QUEUED_REQUEST_AGE
        expired = await expire_stale_manual_queue_requests(db_session, older_than=older_than)
        logger.info("manual_queue_requests_expired", count=len(expired))

    _run_periodic("expire_stale_manual_queue_requests", body)
