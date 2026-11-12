"""
Контейнеры задач (раздел 15.5, 16.2, 19.3 ТЗ): сессии `tracker-session-*` и
script-ноды `tracker-node-*`. Признак «осиротел» один для мониторинга и для
уборки (`services/maintenance_tasks.purge_*`):

- нода — пережила дедлайн из метки `tracker.deadline` (старт + таймаут ноды +
  запас); контейнер без метки — работает дольше ``grace_period``;
- сессия — у её задачи нет пульса сессии: воркер, державший её, завершился.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING

import sqlalchemy as sa

from db.models.tasks import Task
from services.nodes.script import (
    CONTAINER_DEADLINE_LABEL,
    NODE_CONTAINER_PREFIX,
    NODE_TASK_CODE_LABEL,
)
from services.session_container import SESSION_CONTAINER_PREFIX, SESSION_TASK_LABEL
from services.session_heartbeat import is_session_alive

if TYPE_CHECKING:
    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncSession

# Нода без метки дедлайна (запущена до её появления) — зависшая, если
# работает дольше этого запаса.
DEFAULT_ORPHANED_CONTAINER_GRACE_PERIOD = timedelta(minutes=10)

# `docker ps` `{{.CreatedAt}}`: «2026-11-12 10:36:23 +0300 MSK» — имя зоны лишнее.
_CREATED_AT_FORMAT = "%Y-%m-%d %H:%M:%S %z"
_CREATED_AT_PARTS = 3
_FIELD_SEPARATOR = "\t"


class ContainerKind(StrEnum):
    SESSION = "session"
    NODE = "node"


@dataclass(frozen=True, slots=True)
class TrackerContainer:
    name: str
    kind: ContainerKind
    task_id: uuid.UUID | None
    task_code: str | None
    started_at: datetime | None
    orphaned: bool


async def run_docker(*args: str) -> str:
    process = await asyncio.create_subprocess_exec(
        "docker",
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _stderr = await process.communicate()
    return stdout.decode()


def parse_created_at(raw: str) -> datetime | None:
    parts = raw.split()[:_CREATED_AT_PARTS]
    try:
        return datetime.strptime(" ".join(parts), _CREATED_AT_FORMAT)
    except ValueError:
        return None


def _task_id_or_none(raw: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(raw.strip())
    except ValueError:
        return None


async def _list_rows(prefix: str, *labels: str) -> list[list[str]]:
    """Строки `docker ps`: имя, значения меток ``labels`` и время создания."""
    columns = ["{{.Names}}", *(f'{{{{.Label "{label}"}}}}' for label in labels), "{{.CreatedAt}}"]
    listing = await run_docker(
        "ps",
        "--filter",
        f"name={prefix}",
        "--format",
        _FIELD_SEPARATOR.join(columns),
    )
    rows = [line.split(_FIELD_SEPARATOR) for line in listing.splitlines()]
    return [row for row in rows if len(row) == len(columns) and row[0].strip()]


def node_expired(
    *,
    deadline_raw: str,
    started_at: datetime | None,
    now: datetime,
    grace_period: timedelta,
) -> bool:
    if deadline_raw.strip().isdigit():
        return now.timestamp() > int(deadline_raw)
    return started_at is not None and now - started_at > grace_period


async def list_node_containers(
    *,
    now: datetime,
    grace_period: timedelta,
) -> list[TrackerContainer]:
    rows = await _list_rows(NODE_CONTAINER_PREFIX, CONTAINER_DEADLINE_LABEL, NODE_TASK_CODE_LABEL)
    containers: list[TrackerContainer] = []
    for name, deadline_raw, task_code, created_raw in rows:
        started_at = parse_created_at(created_raw)
        containers.append(
            TrackerContainer(
                name=name,
                kind=ContainerKind.NODE,
                task_id=None,
                task_code=task_code.strip() or None,
                started_at=started_at,
                orphaned=node_expired(
                    deadline_raw=deadline_raw,
                    started_at=started_at,
                    now=now,
                    grace_period=grace_period,
                ),
            ),
        )
    return containers


async def list_session_containers(redis_client: Redis) -> list[TrackerContainer]:
    """Контейнер без метки задачи не трогается: чей он — неизвестно."""
    rows = await _list_rows(SESSION_CONTAINER_PREFIX, SESSION_TASK_LABEL)
    containers: list[TrackerContainer] = []
    for name, task_raw, created_raw in rows:
        task_id = _task_id_or_none(task_raw)
        orphaned = task_id is not None and not await is_session_alive(redis_client, task_id)
        containers.append(
            TrackerContainer(
                name=name,
                kind=ContainerKind.SESSION,
                task_id=task_id,
                task_code=None,
                started_at=parse_created_at(created_raw),
                orphaned=orphaned,
            ),
        )
    return containers


async def _task_codes(
    db_session: AsyncSession,
    task_ids: set[uuid.UUID],
) -> dict[uuid.UUID, str]:
    if not task_ids:
        return {}
    rows = await db_session.execute(sa.select(Task.id, Task.code).where(Task.id.in_(task_ids)))
    return {task_id: code for task_id, code in rows}


async def list_task_containers(
    db_session: AsyncSession,
    redis_client: Redis,
    *,
    now: datetime,
) -> list[TrackerContainer]:
    """Раздел 15.5: все контейнеры задач, старые сверху, с кодами задач."""
    sessions = await list_session_containers(redis_client)
    codes = await _task_codes(
        db_session,
        {container.task_id for container in sessions if container.task_id is not None},
    )
    sessions = [
        replace(container, task_code=codes.get(container.task_id))
        if container.task_id is not None
        else container
        for container in sessions
    ]
    nodes = await list_node_containers(
        now=now, grace_period=DEFAULT_ORPHANED_CONTAINER_GRACE_PERIOD
    )
    return sorted(
        [*sessions, *nodes],
        key=lambda container: container.started_at or now,
    )
