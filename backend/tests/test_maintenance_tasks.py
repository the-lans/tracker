import asyncio
import subprocess
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.enums import McpAuthType, NodeLogStatus, NodeLogTriggerType, TaskStatus, UserRole
from db.models.logs import NodeLog
from db.models.mcp import McpServer
from db.models.tasks import Task
from db.models.users import User
from services.crypto import encrypt
from services.maintenance_tasks import (
    check_mcp_server_health,
    find_node_logs_eligible_for_rotation,
    find_tasks_awaiting_input_beyond_threshold,
    find_tasks_needing_cleanup_reminder,
    find_tasks_requiring_remote_control_check,
    health_check_all_mcp_servers,
    purge_orphaned_docker_containers,
    purge_orphaned_playwright_processes,
    revoke_stale_sshfs_keys,
)


async def _make_task(db_session: AsyncSession, *, status: TaskStatus) -> Task:
    user = User(email=f"{uuid.uuid4()}@example.com", role=UserRole.USER)
    db_session.add(user)
    await db_session.flush()
    task = Task(
        code=f"RR-{uuid.uuid4().hex[:5]}",
        title="t",
        description="d",
        created_by=user.id,
        status=status,
    )
    db_session.add(task)
    await db_session.flush()
    return task


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

    found = await find_tasks_requiring_remote_control_check(db_session)
    found_ids = {t.id for t in found}

    assert in_progress.id in found_ids
    assert done.id not in found_ids


async def test_purge_orphaned_docker_containers_stops_stale_and_keeps_fresh() -> None:
    container_name = f"tracker-node-{uuid.uuid4()}"
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


def test_revoke_stale_sshfs_keys_is_a_noop() -> None:
    revoke_stale_sshfs_keys()  # не должно бросать исключений


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
