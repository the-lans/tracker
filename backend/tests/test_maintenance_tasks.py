import asyncio
import subprocess
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.enums import McpAuthType, NodeLogStatus, NodeLogTriggerType, TaskStatus
from db.models.logs import NodeLog
from db.models.mcp import McpServer
from db.models.tasks import Task
from db.models.users import User
from services import maintenance_tasks
from services.crypto import encrypt
from services.maintenance_tasks import (
    awaiting_decision_reminder_key,
    check_mcp_server_health,
    cleanup_reminder_key,
    find_node_logs_eligible_for_rotation,
    find_tasks_awaiting_input_beyond_threshold,
    find_tasks_needing_cleanup_reminder,
    find_tasks_requiring_remote_control_check,
    health_check_all_mcp_servers,
    purge_orphaned_docker_containers,
    purge_orphaned_playwright_processes,
    revoke_stale_sshfs_keys,
    send_awaiting_decision_reminders,
    send_cleanup_reminders,
    stale_ssh_key_reminder_key,
)
from services.nodes.script import CONTAINER_DEADLINE_LABEL, container_deadline
from services.notifications import NotificationEvent
from tests.conftest import ContainerPrefixes
from tests.factories import SAMPLE_ED25519_KEY, make_llm_account, make_task, make_user


async def _make_task(db_session: AsyncSession, *, status: TaskStatus) -> Task:
    return await make_task(db_session, status=status)


async def _set_updated_at(db_session: AsyncSession, task: Task, value: datetime) -> None:
    await db_session.execute(sa.update(Task).where(Task.id == task.id).values(updated_at=value))
    await db_session.commit()
    await db_session.refresh(task)


async def test_find_tasks_needing_cleanup_reminder_matches_old_terminal_task(
    db_session: AsyncSession,
) -> None:
    now = datetime.now(UTC)
    task = await _make_task(db_session, status=TaskStatus.DONE)
    await _set_updated_at(db_session, task, now - timedelta(days=30))

    found = await find_tasks_needing_cleanup_reminder(db_session, now=now, threshold_days=14)

    assert task.id in {t.id for t in found}


async def test_find_tasks_needing_cleanup_reminder_excludes_recent(
    db_session: AsyncSession,
) -> None:
    now = datetime.now(UTC)
    task = await _make_task(db_session, status=TaskStatus.DONE)
    await _set_updated_at(db_session, task, now - timedelta(days=1))

    found = await find_tasks_needing_cleanup_reminder(db_session, now=now, threshold_days=14)

    assert task.id not in {t.id for t in found}


async def test_find_tasks_needing_cleanup_reminder_excludes_already_cleaned(
    db_session: AsyncSession,
) -> None:
    now = datetime.now(UTC)
    task = await _make_task(db_session, status=TaskStatus.DONE)
    await _set_updated_at(db_session, task, now - timedelta(days=30))
    task.repo_cleaned_at = now
    await db_session.commit()

    found = await find_tasks_needing_cleanup_reminder(db_session, now=now, threshold_days=14)

    assert task.id not in {t.id for t in found}


async def test_find_tasks_needing_cleanup_reminder_excludes_non_terminal(
    db_session: AsyncSession,
) -> None:
    now = datetime.now(UTC)
    task = await _make_task(db_session, status=TaskStatus.IN_PROGRESS)
    await _set_updated_at(db_session, task, now - timedelta(days=30))

    found = await find_tasks_needing_cleanup_reminder(db_session, now=now, threshold_days=14)

    assert task.id not in {t.id for t in found}


async def test_find_tasks_awaiting_input_beyond_threshold_matches(db_session: AsyncSession) -> None:
    now = datetime.now(UTC)
    task = await _make_task(db_session, status=TaskStatus.AWAITING_INPUT)
    await _set_updated_at(db_session, task, now - timedelta(hours=8))

    found = await find_tasks_awaiting_input_beyond_threshold(
        db_session,
        now=now,
        threshold=timedelta(hours=4),
    )

    assert task.id in {t.id for t in found}


async def test_find_tasks_awaiting_input_beyond_threshold_excludes_recent(
    db_session: AsyncSession,
) -> None:
    now = datetime.now(UTC)
    task = await _make_task(db_session, status=TaskStatus.PLAN_REVIEW)
    await _set_updated_at(db_session, task, now - timedelta(minutes=5))

    found = await find_tasks_awaiting_input_beyond_threshold(
        db_session,
        now=now,
        threshold=timedelta(hours=4),
    )

    assert task.id not in {t.id for t in found}


async def test_find_tasks_requiring_remote_control_check_matches_active_statuses(
    db_session: AsyncSession,
) -> None:
    in_progress = await _make_task(db_session, status=TaskStatus.IN_PROGRESS)
    done = await _make_task(db_session, status=TaskStatus.DONE)
    scripts_only = await _make_task(db_session, status=TaskStatus.IN_PROGRESS)
    for task in (in_progress, done):
        account = await make_llm_account(db_session, owner_id=task.created_by)
        task.llm_account_id = account.id
    await db_session.flush()

    found = await find_tasks_requiring_remote_control_check(db_session)
    found_ids = {t.id for t in found}

    assert in_progress.id in found_ids
    assert done.id not in found_ids
    # Раздел 6.6: моста нет, но потерянный воркер переводит в `failed` и её.
    assert scripts_only.id in found_ids


async def _run_labelled_container(prefix: str, deadline: int) -> str:
    container_name = f"{prefix}{uuid.uuid4()}"
    process = await asyncio.create_subprocess_exec(
        "docker",
        "run",
        "-d",
        "--name",
        container_name,
        "--label",
        f"{CONTAINER_DEADLINE_LABEL}={deadline}",
        "alpine",
        "sleep",
        "60",
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await process.communicate()
    return container_name


class TestPurgeByDeadline:
    """Раздел 16.2: зависший — переживший свой дедлайн, а не просто «старый»."""

    @pytest.mark.parametrize(
        ("deadline_offset", "grace_period", "purged"),
        [
            (timedelta(hours=1), timedelta(seconds=0), False),
            (-timedelta(seconds=1), timedelta(hours=1), True),
        ],
        ids=["long_running_script_kept", "past_deadline_stopped"],
    )
    async def test_deadline_wins_over_grace(
        self,
        container_prefixes: ContainerPrefixes,
        deadline_offset: timedelta,
        grace_period: timedelta,
        purged: bool,
    ) -> None:
        now = datetime.now(UTC)
        deadline = int((now + deadline_offset).timestamp())
        container_name = await _run_labelled_container(container_prefixes.node, deadline)
        try:
            stopped = await purge_orphaned_docker_containers(now=now, grace_period=grace_period)
            assert (container_name in stopped) is purged
        finally:
            subprocess.run(["docker", "rm", "-f", container_name], capture_output=True)

    def test_deadline_includes_node_timeout(self) -> None:
        assert container_deadline(1800, now=1000.0) > 1000 + 1800


async def test_purge_orphaned_docker_containers_stops_stale_and_keeps_fresh(
    container_prefixes: ContainerPrefixes,
) -> None:
    container_name = f"{container_prefixes.node}{uuid.uuid4()}"
    process = await asyncio.create_subprocess_exec(
        "docker",
        "run",
        "-d",
        "--name",
        container_name,
        "alpine",
        "sleep",
        "60",
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await process.communicate()
    try:
        # С щедрым grace_period контейнер не тронут.
        stopped = await purge_orphaned_docker_containers(grace_period=timedelta(hours=1))
        assert container_name not in stopped

        # С нулевым grace_period контейнер уже "устарел".
        stopped = await purge_orphaned_docker_containers(grace_period=timedelta(seconds=0))
        assert container_name in stopped

        inspect = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Running}}", container_name],
            capture_output=True,
            text=True,
            check=True,
        )
        assert inspect.stdout.strip() == "false"
    finally:
        subprocess.run(["docker", "rm", "-f", container_name], capture_output=True)


def _mcp_server(**overrides: object) -> McpServer:
    defaults: dict[str, object] = {
        "id": uuid.uuid4(),
        "name": "srv",
        "url": "https://mcp.internal/health",
        "auth_type": McpAuthType.NONE,
        "auth_config_encrypted": encrypt(""),
        "is_healthy": False,
        "has_stateful_resource": False,
        "isolation_mode": None,
        "isolation_path_template": None,
    }
    defaults.update(overrides)
    return McpServer(**defaults)


async def test_check_mcp_server_health_true_for_success_response() -> None:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200)),
    )

    assert await check_mcp_server_health(client, _mcp_server()) is True


async def test_check_mcp_server_health_false_for_server_error() -> None:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(503)),
    )

    assert await check_mcp_server_health(client, _mcp_server()) is False


async def test_check_mcp_server_health_false_on_network_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("недоступен", request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    assert await check_mcp_server_health(client, _mcp_server()) is False


async def test_health_check_all_mcp_servers_updates_is_healthy(db_session: AsyncSession) -> None:
    healthy = _mcp_server(url="https://ok.internal")
    unhealthy = _mcp_server(url="https://down.internal")
    db_session.add_all([healthy, unhealthy])
    await db_session.flush()

    def handler(request: httpx.Request) -> httpx.Response:
        if "ok.internal" in str(request.url):
            return httpx.Response(200)
        return httpx.Response(500)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    results = await health_check_all_mcp_servers(db_session, http_client=client)

    assert results[healthy.id] is True
    assert results[unhealthy.id] is False
    assert healthy.is_healthy is True
    assert unhealthy.is_healthy is False


class TestStaleSshKeys:
    """Раздел 16.2: давно не использованный ключ — напоминание владельцу раз за порог."""

    @pytest.fixture
    def sent(self, monkeypatch: pytest.MonkeyPatch) -> list[uuid.UUID]:
        recorded: list[uuid.UUID] = []

        async def record(
            _db: AsyncSession,
            *,
            event: NotificationEvent,
            user_id: uuid.UUID,
            detail: str,
        ) -> None:
            assert event is NotificationEvent.STALE_SSH_KEY
            recorded.append(user_id)

        monkeypatch.setattr(maintenance_tasks, "notify_user_event", record)
        return recorded

    async def _user(self, db_session: AsyncSession, last_used: datetime | None) -> User:
        user = await make_user(db_session)
        user.ssh_public_key = SAMPLE_ED25519_KEY
        user.ssh_key_last_used_at = last_used
        await db_session.flush()
        return user

    async def test_once_per_threshold(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        sent: list[uuid.UUID],
    ) -> None:
        now = datetime.now(UTC)
        user = await self._user(db_session, now - timedelta(days=91))

        first = await revoke_stale_sshfs_keys(db_session, redis_client=redis_client, now=now)
        repeated = await revoke_stale_sshfs_keys(db_session, redis_client=redis_client, now=now)

        assert user.id in first
        assert user.id not in repeated
        assert sent.count(user.id) == 1
        assert await redis_client.ttl(stale_ssh_key_reminder_key(user.id)) > 0
        await redis_client.delete(stale_ssh_key_reminder_key(user.id))

    @pytest.mark.parametrize(
        "last_used_days_ago",
        [10, None],
        ids=["recent", "never_used"],
    )
    async def test_not_stale(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        sent: list[uuid.UUID],
        last_used_days_ago: int | None,
    ) -> None:
        now = datetime.now(UTC)
        last_used = None if last_used_days_ago is None else now - timedelta(days=last_used_days_ago)
        user = await self._user(db_session, last_used)

        reminded = await revoke_stale_sshfs_keys(db_session, redis_client=redis_client, now=now)

        assert user.id not in reminded
        assert user.id not in sent


def test_purge_orphaned_playwright_processes_is_a_noop() -> None:
    purge_orphaned_playwright_processes()  # не должно бросать исключений


async def test_find_node_logs_eligible_for_rotation_matches_old_terminal_task(
    db_session: AsyncSession,
) -> None:
    now = datetime.now(UTC)
    task = await _make_task(db_session, status=TaskStatus.DONE)
    node_log = NodeLog(
        task_id=task.id,
        trigger_type=NodeLogTriggerType.PIPELINE,
        status=NodeLogStatus.SUCCESS,
        started_at=now - timedelta(days=120),
    )
    db_session.add(node_log)
    await db_session.flush()

    eligible = await find_node_logs_eligible_for_rotation(db_session, now=now, threshold_days=90)

    assert node_log.id in eligible


async def test_find_node_logs_eligible_for_rotation_excludes_recent(
    db_session: AsyncSession,
) -> None:
    now = datetime.now(UTC)
    task = await _make_task(db_session, status=TaskStatus.DONE)
    node_log = NodeLog(
        task_id=task.id,
        trigger_type=NodeLogTriggerType.PIPELINE,
        status=NodeLogStatus.SUCCESS,
        started_at=now - timedelta(days=1),
    )
    db_session.add(node_log)
    await db_session.flush()

    eligible = await find_node_logs_eligible_for_rotation(db_session, now=now, threshold_days=90)

    assert node_log.id not in eligible


async def test_find_node_logs_eligible_for_rotation_excludes_non_terminal_task(
    db_session: AsyncSession,
) -> None:
    now = datetime.now(UTC)
    task = await _make_task(db_session, status=TaskStatus.IN_PROGRESS)
    node_log = NodeLog(
        task_id=task.id,
        trigger_type=NodeLogTriggerType.PIPELINE,
        status=NodeLogStatus.SUCCESS,
        started_at=now - timedelta(days=120),
    )
    db_session.add(node_log)
    await db_session.flush()

    eligible = await find_node_logs_eligible_for_rotation(db_session, now=now, threshold_days=90)

    assert node_log.id not in eligible


@pytest.mark.parametrize(
    ("status", "age", "send", "key_of", "event"),
    [
        (
            TaskStatus.DONE,
            timedelta(days=30),
            send_cleanup_reminders,
            cleanup_reminder_key,
            NotificationEvent.CLEANUP_REMINDER,
        ),
        (
            TaskStatus.PLAN_REVIEW,
            timedelta(hours=5),
            send_awaiting_decision_reminders,
            awaiting_decision_reminder_key,
            NotificationEvent.AWAITING_DECISION_REMINDER,
        ),
    ],
    ids=["cleanup", "awaiting_decision"],
)
class TestReminders:
    """Раздел 16.2: напоминание автору — не чаще раза за интервал (ключ Redis)."""

    async def test_once_per_interval(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        monkeypatch: pytest.MonkeyPatch,
        status: TaskStatus,
        age: timedelta,
        send: Any,
        key_of: Any,
        event: NotificationEvent,
    ) -> None:
        sent: list[tuple[NotificationEvent, uuid.UUID]] = []

        async def record(_db: AsyncSession, *, event: NotificationEvent, task: Task) -> None:
            sent.append((event, task.id))

        monkeypatch.setattr(maintenance_tasks, "notify_task_event", record)
        now = datetime.now(UTC)
        task = await _make_task(db_session, status=status)
        await _set_updated_at(db_session, task, now - age)

        first = await send(db_session, redis_client=redis_client, now=now)
        repeated = await send(db_session, redis_client=redis_client, now=now)
        await redis_client.delete(key_of(task.id))
        after_interval = await send(db_session, redis_client=redis_client, now=now)

        assert task.id in first
        assert task.id not in repeated
        assert task.id in after_interval
        assert sent.count((event, task.id)) == 2
        assert await redis_client.ttl(key_of(task.id)) > 0
