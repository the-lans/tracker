"""Обслуживающие периодические задачи раздела 16.2 ТЗ, не покрытые другими
модулями (`autostart.py`, `manual_queue.py`, `remote_control.py`,
`gitlab_sync.py`).

Конкретные пороги (сколько дней считать директорию "устаревшей", какой
таймаут — "зависшим" контейнером) ТЗ не называет числом — это дефолты
реализации, вынесенные в константы ниже и переопределяемые вызывающим
кодом (административный интерфейс, раздел 15.5, "Периодические задачи").

`revoke_stale_sshfs_keys` (решение №18 плана): SFTP-шлюз отмечает вход по
ключу в `users.ssh_key_last_used_at`; владельцу ключа без входа дольше
порога приходит напоминание заменить его. Сам ключ не удаляется.
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
from db.models.users import User
from services.nodes.script import CONTAINER_DEADLINE_LABEL
from services.notifications import NotificationEvent, notify_task_event, notify_user_event

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
# Раздел 16.2: ключ без входа дольше порога помечается для ротации; повторное
# напоминание — не раньше, чем через тот же срок.
STALE_SSH_KEY_THRESHOLD = timedelta(days=90)
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
    """
    Раздел 6.6: `check_remote_control_bridges` — активные задачи с сессией
    Claude Code; у задачи без LLM-аккаунта моста нет (раздел 3.1).
    """
    active_statuses = (
        TaskStatus.IN_PROGRESS,
        TaskStatus.PAUSED,
        TaskStatus.AWAITING_INPUT,
        TaskStatus.PLAN_REVIEW,
    )
    stmt = sa.select(Task).where(
        Task.status.in_(active_statuses),
        Task.llm_account_id.is_not(None),
    )
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
    """Раздел 16.2: останавливает зависшие контейнеры script-нод (`tracker-node-*`).

    Зависший — переживший свой дедлайн из метки `tracker.deadline` (старт +
    `timeout_seconds` ноды + запас, `services/nodes/script.py`): в норме нода
    сама останавливает контейнер по таймауту, а сюда попадают пережившие
    процесс воркера. Контейнер без метки (запущен до её появления) —
    зависший, если работает дольше ``grace_period``.
    """
    now = now or datetime.now(UTC)
    listing = await _run_docker(
        "ps",
        "--filter",
        "name=tracker-node-",
        "--format",
        f'{{{{.Names}}}}\t{{{{.Label "{CONTAINER_DEADLINE_LABEL}"}}}}',
    )

    stopped: list[str] = []
    for line in listing.splitlines():
        name, _, deadline_raw = line.partition("\t")
        if not name.strip():
            continue
        if deadline_raw.strip().isdigit():
            expired = now.timestamp() > int(deadline_raw)
        else:
            started_at_raw = await _run_docker("inspect", "--format", "{{.State.StartedAt}}", name)
            expired = now - _parse_docker_timestamp(started_at_raw) > grace_period
        if expired:
            await _run_docker("stop", name)
            stopped.append(name)
            logger.warning("orphaned_container_purged", container_name=name)
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


def stale_ssh_key_reminder_key(user_id: uuid.UUID) -> str:
    return f"reminder:stale-ssh-key:{user_id}"


async def find_users_with_stale_ssh_keys(db_session: AsyncSession, *, now: datetime) -> list[User]:
    """Ключи без единого входа не помечаются: давность считается от последнего входа."""
    stmt = sa.select(User).where(
        User.is_active == True,  # noqa: E712
        User.ssh_public_key.is_not(None),
        User.ssh_key_last_used_at < now - STALE_SSH_KEY_THRESHOLD,
    )
    return list((await db_session.execute(stmt)).scalars().all())


async def revoke_stale_sshfs_keys(
    db_session: AsyncSession,
    *,
    redis_client: Redis,
    now: datetime,
) -> list[uuid.UUID]:
    """Раздел 16.2: напоминает заменить давно не использованный ключ (`SET NX` + TTL)."""
    reminded: list[uuid.UUID] = []
    interval_seconds = int(STALE_SSH_KEY_THRESHOLD.total_seconds())
    for user in await find_users_with_stale_ssh_keys(db_session, now=now):
        key = stale_ssh_key_reminder_key(user.id)
        if not await redis_client.set(key, "1", nx=True, ex=interval_seconds):
            continue
        await notify_user_event(
            db_session,
            event=NotificationEvent.STALE_SSH_KEY,
            user_id=user.id,
            detail="Ключ SFTP-доступа давно не использовался — замените или удалите его в профиле",
        )
        reminded.append(user.id)
    return reminded


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
