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
from kombu.exceptions import OperationalError

from app_logging.app_logs import write_app_log
from app_logging.config import get_logger
from clients.cliproxy import open_cliproxy_client
from clients.gitlab import GitlabClient
from db.models.enums import (
    AppLogLevel,
    MergeStatus,
    PeriodicRunStatus,
    RepositoryRole,
)
from db.models.periodic import PeriodicTask
from db.models.repositories import Repository
from db.models.tasks import Task, TaskRepository
from db.session import async_session_factory
from services import gitlab_sync, maintenance_tasks, users
from services.app_log_retention import purge_old_app_logs as purge_old_app_logs_pass
from services.autostart import run_scheduled_autostart_check
from services.backup.jobs import backup_job, verify_job
from services.claude_config import resolve_sessions_root
from services.events import purge_old_events
from services.limit_wait import limit_waits_to_resume
from services.llm_account_checks import check_llm_accounts
from services.log_rotation import prune_log_archive, resolve_archive_root, rotate_node_logs
from services.maintenance import maintenance_active
from services.maintenance_tasks import DEFAULT_LOG_ROTATION_THRESHOLD_DAYS
from services.manual_queue import STALE_QUEUED_REQUEST_AGE, expire_stale_manual_queue_requests
from services.periodic_tasks import (
    mark_periodic_task_running,
    notify_periodic_outcome,
    record_periodic_task_run,
)
from services.redis_connection import redis_connection
from services.remote_control import check_session_bridges
from services.system_settings import get_system_settings
from services.task_archive import ArchivePass, RepositoryCleanupPass
from services.task_artifacts import resolve_user_files_root
from services.task_dispatcher import dispatch_queued_tasks, pending_queue_session_ids
from services.task_retention import ArtifactsPass, SessionHistoryPass
from services.task_workspace import resolve_repos_root
from services.volume_usage import store_volume_usage
from tasks.async_runner import run_with_fresh_pool
from tasks.celery_app import (
    BACKUP_TO_S3,
    DISPATCH_READY_TASKS,
    VERIFY_S3_BACKUP,
    celery_app,
    wake_task_dispatcher,
)
from tasks.session_worker import run_task_session

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from sqlalchemy.ext.asyncio import AsyncSession

    from services.task_passes import TaskPass

logger = get_logger("tasks.periodic")

_OWN_EVENT_TASKS = frozenset({BACKUP_TO_S3, VERIFY_S3_BACKUP})


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
        previous_status = periodic_task.last_run_status
        await mark_periodic_task_running(db_session, periodic_task=periodic_task)
        status = PeriodicRunStatus.SUCCESS
        error: str | None = None
        try:
            await body(db_session)
        except Exception as exc:  # noqa: BLE001 — раздел 16.3: любая ошибка периодической задачи логируется, не роняет процесс
            status = PeriodicRunStatus.FAILED
            error = str(exc)
            logger.error("periodic_task_failed", name=name, error=error)
            # Сбой запроса оставляет транзакцию прерванной: без отката итог
            # запуска не записался бы, а статус так и остался бы `running`.
            await db_session.rollback()
            await db_session.refresh(periodic_task)
            await write_app_log(
                level=AppLogLevel.ERROR,
                source=f"periodic.{name}",
                message=str(exc),
                context={},
            )
        await record_periodic_task_run(
            db_session,
            periodic_task=periodic_task,
            status=status,
            ran_at=ran_at,
        )
        # Бэкап и проверка сообщают о своём итоге сами (раздел 20.4).
        if name not in _OWN_EVENT_TASKS:
            await notify_periodic_outcome(
                db_session,
                title=periodic_task.display_name,
                previous=previous_status,
                current=status,
                error=error,
            )


def _run_periodic(name: str, body: Callable[[AsyncSession], Awaitable[None]]) -> None:
    run_with_fresh_pool(_run_periodic_async(name, body))


@celery_app.task(name="check_scheduled_tasks_for_autostart")
def check_scheduled_tasks_for_autostart() -> None:
    async def body(db_session: AsyncSession) -> None:
        result = await run_scheduled_autostart_check(db_session, now=datetime.now(UTC))
        # Раздел 12.2 (п. 2): задача встала в очередь — запускает её воркер очереди.
        if result.queued_task_ids:
            wake_task_dispatcher()

    _run_periodic("check_scheduled_tasks_for_autostart", body)


async def _dispatch(db_session: AsyncSession) -> None:
    async with redis_connection() as redis_client:
        try:
            await dispatch_queued_tasks(db_session, redis_client, now=datetime.now(UTC))
        except Exception:
            # После ошибки запроса сессия может быть в прерванной транзакции.
            await db_session.rollback()
            raise
        finally:
            # Переходы уже закоммичены по одному. Даже при сбое посередине
            # доставляем их; после сбоя брокера повторит следующий проход.
            if not await maintenance_active(redis_client):
                await _deliver_queued_sessions(db_session)


async def _deliver_queued_sessions(db_session: AsyncSession) -> None:
    failure: OperationalError | None = None
    for task_id in await pending_queue_session_ids(db_session):
        try:
            run_task_session.delay(str(task_id), queued_only=True)
        except OperationalError as exc:
            logger.exception("queue_session_delivery_failed", task_id=str(task_id))
            failure = exc
    if failure is not None:
        raise failure


@celery_app.task(name=DISPATCH_READY_TASKS)
def dispatch_ready_tasks() -> None:
    """
    Раздел 14.4: дневной воркер — задачи очереди в свободные слоты.
    """
    _run_periodic(DISPATCH_READY_TASKS, _dispatch)


@celery_app.task(name="dispatch_night_tasks")
def dispatch_night_tasks() -> None:
    """
    Раздел 14.4: ночной воркер — тот же проход по расписанию начала ночного
    окна, чтобы задачи `night_worker` стартовали сразу, а не через 5 минут.
    """
    _run_periodic("dispatch_night_tasks", _dispatch)


@celery_app.task(name="check_llm_account_limits")
def check_llm_account_limits() -> None:
    async def body(db_session: AsyncSession) -> None:
        async with redis_connection() as redis_client, open_cliproxy_client() as cliproxy:
            now = datetime.now(UTC)
            result = await check_llm_accounts(
                db_session,
                redis_client=redis_client,
                cliproxy=cliproxy,
                now=now,
            )
            # Раздел 19.7: страховка отложенного продолжения ждущих лимита задач.
            resumed = await limit_waits_to_resume(
                db_session,
                redis_client=redis_client,
                cliproxy=cliproxy,
                now=now,
            )
        for task_id in resumed:
            run_task_session.delay(str(task_id), limit_resume=True)
        logger.info(
            "llm_accounts_checked",
            restored=len(result.restored),
            polled=len(result.polled),
            login_required=len(result.login_required),
            cancelled_logins=result.cancelled_logins,
            limit_waits_resumed=len(resumed),
        )

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


def _run_task_pass(
    name: str,
    event: str,
    make_pass: Callable[[AsyncSession, datetime], TaskPass],
) -> None:
    """
    Проход по завершённым задачам (`services/task_passes.py`) и его итог в лог.
    """

    async def body(db_session: AsyncSession) -> None:
        async with redis_connection() as redis_client:
            result = await make_pass(db_session, datetime.now(UTC)).run(redis_client)
        logger.info(
            event,
            done=len(result.done),
            skipped=len(result.skipped),
            lock_busy=result.lock_busy,
        )

    _run_periodic(name, body)


@celery_app.task(name="archive_finished_tasks")
def archive_finished_tasks() -> None:
    """Раздел 14.2: завершённые задачи старше срока автора уходят в архив."""
    _run_task_pass(
        "archive_finished_tasks",
        "finished_tasks_archived",
        lambda db_session, now: ArchivePass(db_session, now=now),
    )


@celery_app.task(name="cleanup_finished_task_repositories")
def cleanup_finished_task_repositories() -> None:
    """Раздел 14.2: репозитории завершённых задач очищаются через срок автора."""
    _run_task_pass(
        "cleanup_finished_task_repositories",
        "finished_task_repositories_cleaned",
        lambda db_session, now: RepositoryCleanupPass(
            db_session,
            now=now,
            repos_root=resolve_repos_root(),
        ),
    )


@celery_app.task(name="cleanup_archived_task_sessions")
def cleanup_archived_task_sessions() -> None:
    """Раздел 6.4: история сессии задачи, давно лежащей в архиве, удаляется."""
    _run_task_pass(
        "cleanup_archived_task_sessions",
        "archived_task_sessions_cleaned",
        lambda db_session, now: SessionHistoryPass(
            db_session,
            now=now,
            root=resolve_sessions_root(),
        ),
    )


@celery_app.task(name="cleanup_archived_task_artifacts")
def cleanup_archived_task_artifacts() -> None:
    """Раздел 14.3: артефакты архивной задачи удаляются через срок автора."""
    _run_task_pass(
        "cleanup_archived_task_artifacts",
        "archived_task_artifacts_cleaned",
        lambda db_session, now: ArtifactsPass(
            db_session,
            now=now,
            root=resolve_user_files_root(),
        ),
    )


@celery_app.task(name="purge_old_app_logs")
def purge_old_app_logs() -> None:
    """
    Раздел 17.2: записи `app_logs` старше срока из системных настроек удаляются.
    """

    async def body(db_session: AsyncSession) -> None:
        settings = await get_system_settings(db_session)
        deleted = await purge_old_app_logs_pass(
            db_session,
            now=datetime.now(UTC),
            days=settings.app_logs_retention_days,
        )
        logger.info("app_logs_purged", deleted=deleted)

    _run_periodic("purge_old_app_logs", body)


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
                client_for=lambda access: GitlabClient(
                    base_url=access.base_url,
                    token=access.token,
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
        now = datetime.now(UTC)
        result = await rotate_node_logs(
            db_session,
            archive_root=resolve_archive_root(),
            now=now,
        )
        logger.info(
            "node_logs_rotated",
            files=len(result.archived_files),
            deleted=result.deleted_count,
        )
        # Раздел 18.4: лента событий хранится столько же, сколько `node_logs`.
        purged = await purge_old_events(
            db_session,
            now=now,
            threshold_days=DEFAULT_LOG_ROTATION_THRESHOLD_DAYS,
        )
        logger.info("events_purged", deleted=purged)
        await prune_log_archive(archive_root=resolve_archive_root(), now=now)

    _run_periodic("rotate_task_logs", body)


@celery_app.task(name="measure_volume_usage")
def measure_volume_usage() -> None:
    async def body(_db_session: AsyncSession) -> None:
        async with redis_connection() as redis_client:
            snapshot = await store_volume_usage(redis_client, now=datetime.now(UTC))
        logger.info("volume_usage_measured", sizes=snapshot.sizes)

    _run_periodic("measure_volume_usage", body)


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


@celery_app.task(name=BACKUP_TO_S3)
def backup_to_s3() -> None:
    """Раздел 20.4: ежедневный бэкап в S3 — сервис `backup-worker`, очередь `backups`."""

    async def body(db_session: AsyncSession) -> None:
        await backup_job(db_session, now=datetime.now(UTC))

    _run_periodic(BACKUP_TO_S3, body)


@celery_app.task(name=VERIFY_S3_BACKUP)
def verify_s3_backup() -> None:
    """Раздел 20.4: еженедельная проверка восстановления последней копии."""

    async def body(db_session: AsyncSession) -> None:
        await verify_job(db_session)

    _run_periodic(VERIFY_S3_BACKUP, body)
