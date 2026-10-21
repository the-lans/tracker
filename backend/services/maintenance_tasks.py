"""Обслуживающие периодические задачи раздела 16.2 ТЗ, не покрытые другими
модулями (`autostart.py`, `manual_queue.py`, `remote_control.py`,
`gitlab_sync.py`).

Конкретные пороги (сколько дней считать директорию "устаревшей", какой
таймаут — "зависшим" контейнером) ТЗ не называет числом — это дефолты
реализации, вынесенные в константы ниже и переопределяемые вызывающим
кодом (административный интерфейс, раздел 15.5, "Периодические задачи").

`revoke_stale_sshfs_keys` — заглушка (решения №4 и №16 плана реализации):
ключ sshfs ставит на сервер администратор, и у трекера нет данных о том,
каким ключом и когда пользовались, — помечать для ротации нечего.
`deprovision_inactive_users` — в `services/users.py`.

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
from services.notifications import NotificationEvent, notify_task_event

if TYPE_CHECKING:
    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger("maintenance_tasks")

DEFAULT_STALE_WORKTREE_THRESHOLD_DAYS = 14
DEFAULT_AWAITING_INPUT_THRESHOLD = timedelta(hours=4)
# Раздел 16.2: напоминание о директории — не чаще раза в неделю на задачу,
# о решении — не чаще раза за порог ожидания.
CLEANUP_REMINDER_INTERVAL = timedelta(days=7)
AWAITING_DECISION_REMINDER_INTERVAL = DEFAULT_AWAITING_INPUT_THRESHOLD
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


def cleanup_reminder_key(task_id: uuid.UUID) -> str:
    return f"reminder:cleanup:{task_id}"


def awaiting_decision_reminder_key(task_id: uuid.UUID) -> str:
    return f"reminder:awaiting:{task_id}"


async def _remind_once(
    db_session: AsyncSession,
    *,
    redis_client: Redis,
    task: Task,
    key: str,
    interval: timedelta,
    event: NotificationEvent,
) -> bool:
    """`SET NX` с TTL: повторный запуск в пределах интервала push не шлёт (раздел 17.4)."""
    if not await redis_client.set(key, "1", nx=True, ex=int(interval.total_seconds())):
        return False
    await notify_task_event(db_session, event=event, task=task)
    return True


async def send_cleanup_reminders(
    db_session: AsyncSession,
    *,
    redis_client: Redis,
    now: datetime,
) -> list[uuid.UUID]:
    """Раздел 16.2: `cleanup_stale_worktrees` — напоминание автору задачи."""
    reminded: list[uuid.UUID] = []
    for task in await find_tasks_needing_cleanup_reminder(db_session, now=now):
        if await _remind_once(
            db_session,
            redis_client=redis_client,
            task=task,
            key=cleanup_reminder_key(task.id),
            interval=CLEANUP_REMINDER_INTERVAL,
            event=NotificationEvent.CLEANUP_REMINDER,
        ):
            reminded.append(task.id)
    return reminded


async def send_awaiting_decision_reminders(
    db_session: AsyncSession,
    *,
    redis_client: Redis,
    now: datetime,
) -> list[uuid.UUID]:
    """Раздел 16.2: `detect_awaiting_input_timeout` — повторное уведомление автору."""
    reminded: list[uuid.UUID] = []
    for task in await find_tasks_awaiting_input_beyond_threshold(db_session, now=now):
        if await _remind_once(
            db_session,
            redis_client=redis_client,
            task=task,
            key=awaiting_decision_reminder_key(task.id),
            interval=AWAITING_DECISION_REMINDER_INTERVAL,
            event=NotificationEvent.AWAITING_DECISION_REMINDER,
        ):
            reminded.append(task.id)
    return reminded


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
    """
    Заглушка (решения №4 и №16 плана реализации): ключ ставит на сервер
    администратор, данных об использовании ключей sshd у трекера нет.
    Точка расширения для `User-Provisioner`.
    """
    logger.info("revoke_stale_sshfs_keys_noop")


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
    limit: int | None = None,
) -> list[uuid.UUID]:
    """
    Раздел 16.2: `rotate_task_logs` — какие записи `node_logs` архивировать.

    Только задачи в `done` и записи старше ``threshold_days``. Задачу в
    `failed` можно перезапустить, а перезапуск опирается на её историю:
    успешные записи пройденных нод (переход в `done`, правило 14), их вывод
    для подстановок и точку возобновления. Саму выгрузку делает
    `services/log_rotation.py`.
    """
    cutoff = now - timedelta(days=threshold_days)
    stmt = (
        sa.select(NodeLog.id)
        .join(Task, Task.id == NodeLog.task_id)
        .where(
            Task.status == TaskStatus.DONE,
            NodeLog.started_at < cutoff,
        )
        .order_by(NodeLog.started_at, NodeLog.id)
        .limit(limit)
    )
    return list((await db_session.execute(stmt)).scalars().all())
