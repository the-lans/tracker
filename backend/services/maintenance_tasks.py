"""Обслуживающие периодические задачи раздела 16.2 ТЗ, не покрытые другими
модулями (`autostart.py`, `manual_queue.py`, `remote_control.py`,
`gitlab_sync.py`).

Конкретные пороги (сколько дней считать директорию "устаревшей", какой
таймаут — "зависшим" контейнером) ТЗ не называет числом — это дефолты
реализации, вынесенные в константы ниже и переопределяемые вызывающим
кодом (административный интерфейс, раздел 15.5, "Периодические задачи").

`revoke_stale_sshfs_keys` и `deprovision_inactive_users` реализованы как
заглушки (решение №4 плана реализации: провижининг ОС-пользователей вне
периметра проекта) — только логируют факт вызова, не выполняют реальных
действий, поскольку обслуживать им нечего без реального провижининга.

`purge_orphaned_playwright_processes` — тоже заглушка, но по другой
причине: она предполагает поиск процессов браузера, физически работающих на
стороне конкретного MCP-сервера (раздел 10), а топология его развёртывания
(собственный контейнер backend не контролирует) не определена этим
проектом, поэтому "найти и завершить" здесь нечем управлять напрямую.
Задача логирует факт вызова и оставлена точкой расширения.
`check_llm_account_limits` — в `services/llm_accounts.py`.
"""

from __future__ import annotations

import asyncio
import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import httpx
import sqlalchemy as sa

from app_logging.config import get_logger
from db.models.enums import TaskStatus
from db.models.logs import NodeLog
from db.models.mcp import McpServer
from db.models.tasks import Task

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger("maintenance_tasks")

DEFAULT_STALE_WORKTREE_THRESHOLD_DAYS = 14
DEFAULT_AWAITING_INPUT_THRESHOLD = timedelta(hours=4)
DEFAULT_ORPHANED_CONTAINER_GRACE_PERIOD = timedelta(minutes=10)
_MCP_HEALTH_CHECK_TIMEOUT_SECONDS = 5.0


async def find_tasks_needing_cleanup_reminder(
    db_session: AsyncSession,
    *,
    now: datetime,
    threshold_days: int = DEFAULT_STALE_WORKTREE_THRESHOLD_DAYS,
) -> list[Task]:
    """Раздел 16.2: `cleanup_stale_worktrees` — терминальный статус, директория не очищена."""
    cutoff = now - timedelta(days=threshold_days)
    stmt = sa.select(Task).where(
        Task.status.in_((TaskStatus.DONE, TaskStatus.FAILED)),
        Task.repo_cleaned_at.is_(None),
        Task.updated_at < cutoff,
    )
    return list((await db_session.execute(stmt)).scalars().all())


async def find_tasks_awaiting_input_beyond_threshold(
    db_session: AsyncSession,
    *,
    now: datetime,
    threshold: timedelta = DEFAULT_AWAITING_INPUT_THRESHOLD,
) -> list[Task]:
    """Раздел 16.2: `detect_awaiting_input_timeout`."""
    cutoff = now - threshold
    stmt = sa.select(Task).where(
        Task.status.in_((TaskStatus.AWAITING_INPUT, TaskStatus.PLAN_REVIEW)),
        Task.updated_at < cutoff,
    )
    return list((await db_session.execute(stmt)).scalars().all())


async def find_tasks_requiring_remote_control_check(db_session: AsyncSession) -> list[Task]:
    """Раздел 6.6: `check_remote_control_bridges` — активные задачи."""
    active_statuses = (
        TaskStatus.IN_PROGRESS,
        TaskStatus.PAUSED,
        TaskStatus.AWAITING_INPUT,
        TaskStatus.PLAN_REVIEW,
    )
    stmt = sa.select(Task).where(Task.status.in_(active_statuses))
    return list((await db_session.execute(stmt)).scalars().all())


_FRACTIONAL_SECONDS_RE = re.compile(r"(\.\d{6})\d*")


def _parse_docker_timestamp(raw: str) -> datetime:
    """`docker inspect` отдаёт RFC3339 с наносекундами — `datetime.fromisoformat`
    понимает только до микросекунд, лишние цифры дробной части обрезаются."""
    normalized = raw.strip().replace("Z", "+00:00")
    normalized = _FRACTIONAL_SECONDS_RE.sub(r"\1", normalized)
    return datetime.fromisoformat(normalized)


async def _run_docker(*args: str) -> str:
    process = await asyncio.create_subprocess_exec(
        "docker",
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _stderr = await process.communicate()
    return stdout.decode()


async def purge_orphaned_docker_containers(
    *,
    now: datetime | None = None,
    grace_period: timedelta = DEFAULT_ORPHANED_CONTAINER_GRACE_PERIOD,
) -> list[str]:
    """Раздел 16.2: останавливает контейнеры script-нод (`tracker-node-*`,
    см. `services/nodes/script.py`), запущенные дольше ``grace_period``.

    В норме script-нода сама останавливает свой контейнер по истечении
    `timeout_seconds` (`services/nodes/script.py`) — эта задача ловит те,
    что пережили родительский процесс backend (например, при аварийном
    перезапуске воркера).
    """
    now = now or datetime.now(UTC)
    names_output = await _run_docker(
        "ps",
        "--filter",
        "name=tracker-node-",
        "--format",
        "{{.Names}}",
    )
    names = [name for name in names_output.splitlines() if name.strip()]

    stopped: list[str] = []
    for name in names:
        started_at_raw = await _run_docker("inspect", "--format", "{{.State.StartedAt}}", name)
        started_at = _parse_docker_timestamp(started_at_raw)
        if now - started_at > grace_period:
            await _run_docker("stop", name)
            stopped.append(name)
            logger.warning("orphaned_container_purged", container_name=name, started_at=started_at)
    return stopped


async def check_mcp_server_health(http_client: httpx.AsyncClient, mcp_server: McpServer) -> bool:
    """Раздел 16.2: `health_check_mcp_servers` — один сервер."""
    try:
        response = await http_client.get(mcp_server.url, timeout=_MCP_HEALTH_CHECK_TIMEOUT_SECONDS)
    except httpx.TransportError:
        return False
    return response.status_code < 500


async def health_check_all_mcp_servers(
    db_session: AsyncSession,
    *,
    http_client: httpx.AsyncClient,
) -> dict[uuid.UUID, bool]:
    stmt = sa.select(McpServer)
    servers = list((await db_session.execute(stmt)).scalars().all())
    results: dict[uuid.UUID, bool] = {}
    for server in servers:
        is_healthy = await check_mcp_server_health(http_client, server)
        server.is_healthy = is_healthy
        results[server.id] = is_healthy
    if servers:
        await db_session.commit()
    return results


def revoke_stale_sshfs_keys() -> None:
    """Заглушка (решение №4 плана реализации): провижининг SSH-ключей sshfs
    вне периметра проекта — нечего отзывать без реального провижининга."""
    logger.info("revoke_stale_sshfs_keys_noop")


def deprovision_inactive_users() -> None:
    """Заглушка (решение №4 плана реализации): провижининг ОС-пользователей
    вне периметра проекта — нечего деактивировать без реального провижининга."""
    logger.info("deprovision_inactive_users_noop")


def purge_orphaned_playwright_processes() -> None:
    """Заглушка: топология развёртывания конкретного MCP-сервера, физически
    держащего процесс браузера, вне контроля backend (см. docstring модуля)."""
    logger.info("purge_orphaned_playwright_processes_noop")


DEFAULT_LOG_ROTATION_THRESHOLD_DAYS = 90


async def find_node_logs_eligible_for_rotation(
    db_session: AsyncSession,
    *,
    now: datetime,
    threshold_days: int = DEFAULT_LOG_ROTATION_THRESHOLD_DAYS,
) -> list[uuid.UUID]:
    """Раздел 16.2: `rotate_task_logs`.

    Возвращает id записей `node_logs`, подходящих под архивацию — только
    для задач в терминальном статусе (`done`/`failed`), старше
    ``threshold_days``. Само физическое архивирование (выгрузка в холодное
    хранилище, формат) — открытый инфраструктурный вопрос, ТЗ не называет
    ни формат, ни место хранения; удаление истории без явного решения об
    этом было бы необратимым и вне того, что здесь оправданно решать
    самостоятельно.
    """
    cutoff = now - timedelta(days=threshold_days)
    stmt = (
        sa.select(NodeLog.id)
        .join(Task, Task.id == NodeLog.task_id)
        .where(
            Task.status.in_((TaskStatus.DONE, TaskStatus.FAILED)),
            NodeLog.started_at < cutoff,
        )
    )
    return list((await db_session.execute(stmt)).scalars().all())
