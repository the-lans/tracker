"""
Сводка состояния сервера для страницы «Мониторинг» (раздел 15.5 ТЗ):
PostgreSQL, Redis, LLM-прокси, воркеры по очередям Celery и длина очередей,
очередь ручных запросов, версия и время развёртывания, флаг обслуживания,
последний бэкап и последняя проверка восстановления.

Недоступная зависимость — строка с причиной, а не ошибка всего запроса:
сводка нужна именно тогда, когда что-то сломалось.
"""

from __future__ import annotations

import os
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

import sqlalchemy as sa
from redis.exceptions import RedisError
from sqlalchemy.exc import SQLAlchemyError

from app_logging.config import get_logger
from db.models.enums import BackupRunKind, ManualRequestStatus
from db.models.prompts import TaskManualRequestQueue
from services.backup.runs import latest_run
from services.errors import ExternalServiceError
from services.maintenance import MAINTENANCE_KEY

if TYPE_CHECKING:
    from collections.abc import Sequence

    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncSession

    from clients.cliproxy import CliproxyManagementClient
    from db.models.backups import BackupRun

logger = get_logger("server_status")

# Раздел 20.7: коммит образа и время развёртывания пишет `deploy/install.sh`.
VERSION_ENV = "GIT_SHA"
DEPLOYED_AT_ENV = "DEPLOYED_AT"
UNKNOWN_VERSION = "unknown"

# Ответ `celery inspect active_queues`: имя воркера -> очереди, которые он слушает.
InspectQueuesResponse = dict[str, list[dict[str, Any]]]


class Dependency(StrEnum):
    POSTGRES = "postgres"
    REDIS = "redis"
    LLM_PROXY = "llm_proxy"


@dataclass(frozen=True, slots=True)
class DependencyStatus:
    name: Dependency
    ok: bool
    error: str | None = None


@dataclass(frozen=True, slots=True)
class QueueStatus:
    name: str
    workers: int
    # Сообщений в брокере; None — Redis недоступен.
    pending: int | None


@dataclass(frozen=True, slots=True)
class ServerOverview:
    dependencies: list[DependencyStatus]
    queues: list[QueueStatus]
    manual_requests_queued: int
    manual_requests_processing: int
    version: str
    deployed_at: datetime | None
    # None — флаг не прочитан (Redis недоступен).
    maintenance: bool | None
    last_backup: BackupRun | None
    last_verify: BackupRun | None


async def _postgres_status(db_session: AsyncSession) -> DependencyStatus:
    try:
        await db_session.execute(sa.text("SELECT 1"))
    except SQLAlchemyError as exc:
        await db_session.rollback()
        return DependencyStatus(Dependency.POSTGRES, ok=False, error=type(exc).__name__)
    return DependencyStatus(Dependency.POSTGRES, ok=True)


async def _proxy_status(cliproxy: CliproxyManagementClient) -> DependencyStatus:
    try:
        await cliproxy.list_credentials()
    except ExternalServiceError as exc:
        return DependencyStatus(Dependency.LLM_PROXY, ok=False, error=exc.message)
    return DependencyStatus(Dependency.LLM_PROXY, ok=True)


@dataclass(frozen=True, slots=True)
class _RedisSnapshot:
    status: DependencyStatus
    pending: dict[str, int]
    maintenance: bool | None


async def _redis_snapshot(redis_client: Redis, queue_names: Sequence[str]) -> _RedisSnapshot:
    try:
        await redis_client.ping()
        # Брокер Celery на Redis держит сообщения очереди в списке с её именем.
        pending = {name: int(await redis_client.llen(name)) for name in queue_names}
        maintenance = bool(await redis_client.exists(MAINTENANCE_KEY))
    except (RedisError, OSError) as exc:
        logger.warning("server_status_redis_unavailable", error=str(exc))
        return _RedisSnapshot(
            status=DependencyStatus(Dependency.REDIS, ok=False, error=type(exc).__name__),
            pending={},
            maintenance=None,
        )
    return _RedisSnapshot(
        status=DependencyStatus(Dependency.REDIS, ok=True),
        pending=pending,
        maintenance=maintenance,
    )


def workers_per_queue(active_queues: InspectQueuesResponse | None) -> Counter[str]:
    """Сколько ответивших воркеров слушает каждую очередь."""
    counter: Counter[str] = Counter()
    for queues in (active_queues or {}).values():
        counter.update({queue["name"] for queue in queues if "name" in queue})
    return counter


async def _manual_request_counts(db_session: AsyncSession) -> Counter[ManualRequestStatus]:
    rows = await db_session.execute(
        sa.select(TaskManualRequestQueue.status, sa.func.count())
        .where(
            TaskManualRequestQueue.status.in_(
                [ManualRequestStatus.QUEUED, ManualRequestStatus.PROCESSING],
            ),
        )
        .group_by(TaskManualRequestQueue.status),
    )
    return Counter({status: count for status, count in rows})


def deployed_at_from_env() -> datetime | None:
    raw = os.environ.get(DEPLOYED_AT_ENV, "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


async def server_overview(
    db_session: AsyncSession,
    redis_client: Redis,
    cliproxy: CliproxyManagementClient,
    *,
    queue_names: Sequence[str],
    active_queues: InspectQueuesResponse | None,
) -> ServerOverview:
    postgres = await _postgres_status(db_session)
    redis = await _redis_snapshot(redis_client, queue_names)
    workers = workers_per_queue(active_queues)
    manual = await _manual_request_counts(db_session) if postgres.ok else Counter()
    return ServerOverview(
        dependencies=[postgres, redis.status, await _proxy_status(cliproxy)],
        queues=[
            QueueStatus(name=name, workers=workers[name], pending=redis.pending.get(name))
            for name in queue_names
        ],
        manual_requests_queued=manual[ManualRequestStatus.QUEUED],
        manual_requests_processing=manual[ManualRequestStatus.PROCESSING],
        version=os.environ.get(VERSION_ENV) or UNKNOWN_VERSION,
        deployed_at=deployed_at_from_env(),
        maintenance=redis.maintenance,
        last_backup=await latest_run(db_session, kind=BackupRunKind.BACKUP)
        if postgres.ok
        else None,
        last_verify=await latest_run(db_session, kind=BackupRunKind.VERIFY)
        if postgres.ok
        else None,
    )
