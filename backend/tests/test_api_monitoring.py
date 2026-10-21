"""`api/monitoring.py` — раздел 15.5, 17.2 ТЗ."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.enums import AppLogLevel, NodeLogStatus, NodeLogTriggerType, NodeType, UserRole
from db.models.logs import AppLog, NodeLog
from db.models.pipelines import Node
from db.models.tasks import Task
from db.models.users import User

if TYPE_CHECKING:
    from httpx import AsyncClient


async def test_filters_by_level(admin_client: AsyncClient, db_session: AsyncSession) -> None:
    db_session.add_all(
        [
            AppLog(level=AppLogLevel.ERROR, source="tasks.periodic", message="упало", context={}),
            AppLog(level=AppLogLevel.INFO, source="tasks.periodic", message="ок", context={}),
        ],
    )
    await db_session.flush()

    response = await admin_client.get("/app-logs", params={"level": AppLogLevel.ERROR.value})

    assert response.status_code == 200
    entries = response.json()
    assert all(entry["level"] == AppLogLevel.ERROR.value for entry in entries)
    assert any(entry["message"] == "упало" for entry in entries)


async def test_non_admin_cannot_view_app_logs(authed_client: AsyncClient) -> None:
    response = await authed_client.get("/app-logs")

    assert response.status_code == 403


async def _make_task(db_session: AsyncSession, code: str) -> Task:
    user = User(email=f"{uuid.uuid4()}@example.com", role=UserRole.USER)
    db_session.add(user)
    await db_session.flush()
    task = Task(code=code, title="t", description="d", created_by=user.id)
    db_session.add(task)
    await db_session.flush()
    return task


class TestAppLogTaskAndSourceFilter:
    """Раздел 15.5, 17.2: фильтр по задаче (код RR-XXXXX) и источнику."""

    async def test_by_task_code_and_source(
        self,
        admin_client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        task = await _make_task(db_session, "RR-31001")
        other = await _make_task(db_session, "RR-31002")
        db_session.add_all(
            [
                AppLog(
                    level=AppLogLevel.ERROR,
                    source="autostart",
                    message="своя",
                    context={},
                    task_id=task.id,
                ),
                AppLog(
                    level=AppLogLevel.ERROR,
                    source="session_worker",
                    message="другой источник",
                    context={},
                    task_id=task.id,
                ),
                AppLog(
                    level=AppLogLevel.ERROR,
                    source="autostart",
                    message="чужая",
                    context={},
                    task_id=other.id,
                ),
            ],
        )
        await db_session.flush()

        response = await admin_client.get(
            "/app-logs",
            params={"task_code": " RR-31001 ", "source": "autostart"},
        )

        assert [entry["message"] for entry in response.json()] == ["своя"]


class TestAppLogDateFilter:
    async def test_period(self, admin_client: AsyncClient, db_session: AsyncSession) -> None:
        now = datetime.now(UTC)
        db_session.add_all(
            [
                AppLog(
                    level=AppLogLevel.INFO,
                    source="s",
                    message="давнее",
                    context={},
                    created_at=now - timedelta(days=3),
                ),
                AppLog(level=AppLogLevel.INFO, source="s", message="свежее", context={}),
            ],
        )
        await db_session.flush()

        response = await admin_client.get(
            "/app-logs",
            params={"created_from": (now - timedelta(days=1)).isoformat(), "source": "s"},
        )

        assert response.status_code == 200
        assert [entry["message"] for entry in response.json()] == ["свежее"]


class TestNodeRuns:
    async def test_filters_and_fields(
        self,
        admin_client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        task = await _make_task(db_session, f"RR-{uuid.uuid4().hex[:6]}")
        other = await _make_task(db_session, f"RR-{uuid.uuid4().hex[:6]}")
        node = Node(
            name="Сборка",
            node_type=NodeType.PLAIN_PROMPT,
            is_library_item=True,
            created_by=task.created_by,
        )
        db_session.add(node)
        await db_session.flush()
        db_session.add_all(
            [
                NodeLog(
                    task_id=task.id,
                    node_id=node.id,
                    trigger_type=NodeLogTriggerType.PIPELINE,
                    status=NodeLogStatus.FAILED,
                    started_at=datetime.now(UTC),
                ),
                NodeLog(
                    task_id=task.id,
                    trigger_type=NodeLogTriggerType.FREEFORM_MANUAL,
                    status=NodeLogStatus.SUCCESS,
                    started_at=datetime.now(UTC),
                ),
                NodeLog(
                    task_id=other.id,
                    trigger_type=NodeLogTriggerType.PIPELINE,
                    status=NodeLogStatus.FAILED,
                    started_at=datetime.now(UTC),
                ),
            ],
        )
        await db_session.flush()

        response = await admin_client.get(
            "/monitoring/node-runs",
            params={"task_id": str(task.id), "status": NodeLogStatus.FAILED.value},
        )

        assert response.status_code == 200
        [row] = response.json()
        assert row["task_code"] == task.code
        assert row["node_name"] == "Сборка"
        assert row["trigger_type"] == NodeLogTriggerType.PIPELINE.value

    async def test_limit(self, admin_client: AsyncClient, db_session: AsyncSession) -> None:
        task = await _make_task(db_session, f"RR-{uuid.uuid4().hex[:6]}")
        db_session.add_all(
            [
                NodeLog(
                    task_id=task.id,
                    trigger_type=NodeLogTriggerType.PIPELINE,
                    status=NodeLogStatus.SUCCESS,
                )
                for _ in range(3)
            ],
        )
        await db_session.flush()

        response = await admin_client.get(
            "/monitoring/node-runs",
            params={"task_id": str(task.id), "limit": 2},
        )

        assert len(response.json()) == 2


class TestActiveCeleryTasks:
    async def test_lists_worker_tasks_with_task_code(
        self,
        admin_client: AsyncClient,
        db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        task = await _make_task(db_session, f"RR-{uuid.uuid4().hex[:6]}")
        started = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)
        raw = {
            "celery@worker-2": [
                {"id": "c-2", "name": "sync_gitlab_merge_status", "args": [], "time_start": None},
            ],
            "celery@worker-1": [
                {
                    "id": "c-1",
                    "name": "run_task_session",
                    "args": [str(task.id)],
                    "time_start": started.timestamp(),
                },
            ],
        }
        monkeypatch.setattr("api.monitoring._inspect_active", lambda: raw)

        response = await admin_client.get("/monitoring/celery-tasks")

        assert response.status_code == 200
        assert response.json() == [
            {
                "worker": "celery@worker-1",
                "celery_task_id": "c-1",
                "name": "run_task_session",
                "started_at": "2026-10-20T12:00:00Z",
                "task_id": str(task.id),
                "task_code": task.code,
            },
            {
                "worker": "celery@worker-2",
                "celery_task_id": "c-2",
                "name": "sync_gitlab_merge_status",
                "started_at": None,
                "task_id": None,
                "task_code": None,
            },
        ]

    async def test_no_workers_answered(
        self,
        admin_client: AsyncClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr("api.monitoring._inspect_active", lambda: None)

        response = await admin_client.get("/monitoring/celery-tasks")

        assert response.json() == []

    @pytest.mark.parametrize("path", ["/monitoring/celery-tasks", "/monitoring/node-runs"])
    async def test_admin_only(self, authed_client: AsyncClient, path: str) -> None:
        response = await authed_client.get(path)

        assert response.status_code == 403
