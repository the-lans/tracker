"""
Воркер собирает контейнеры; публичный API читает только снимок Redis.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import TYPE_CHECKING

from pydantic import AwareDatetime, BaseModel, ValidationError
from redis.exceptions import RedisError

from services.container_monitor import TrackerContainer, list_task_containers
from services.errors import ServiceUnavailableError

if TYPE_CHECKING:
    from datetime import datetime

    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncSession

CONTAINERS_KEY = "monitoring:task_containers:v1"
SNAPSHOT_MAX_AGE = timedelta(minutes=2)
_COLLECT_TIMEOUT_SECONDS = 10
_UNAVAILABLE = "Список контейнеров временно недоступен: нет актуального снимка воркера"


class ContainerSnapshot(BaseModel):
    measured_at: AwareDatetime
    containers: list[TrackerContainer]


async def store_container_snapshot(
    db_session: AsyncSession, redis_client: Redis, *, now: datetime
) -> ContainerSnapshot:
    async with asyncio.timeout(_COLLECT_TIMEOUT_SECONDS):
        containers = await list_task_containers(db_session, redis_client, now=now)
    snapshot = ContainerSnapshot(measured_at=now, containers=containers)
    await redis_client.set(
        CONTAINERS_KEY, snapshot.model_dump_json(), ex=int(SNAPSHOT_MAX_AGE.total_seconds())
    )
    return snapshot


async def read_container_snapshot(redis_client: Redis, *, now: datetime) -> list[TrackerContainer]:
    try:
        raw = await redis_client.get(CONTAINERS_KEY)
        if raw is None:
            raise ServiceUnavailableError(_UNAVAILABLE)
        snapshot = ContainerSnapshot.model_validate_json(raw)
    except (RedisError, ValidationError) as exc:
        raise ServiceUnavailableError(_UNAVAILABLE) from exc
    if not timedelta(0) <= now - snapshot.measured_at < SNAPSHOT_MAX_AGE:
        raise ServiceUnavailableError(_UNAVAILABLE)
    return snapshot.containers
