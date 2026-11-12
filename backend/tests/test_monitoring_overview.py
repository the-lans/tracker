"""
Блоки страницы «Мониторинг» (раздел 15.5 ТЗ): сводка сервера, статистика нод,
расход LLM, место на диске, контейнеры задач.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from db.models.backups import BackupRun
from db.models.enums import (
    AppLogLevel,
    BackupRunKind,
    BackupRunStatus,
    ManualRequestStatus,
    ManualRequestType,
    NodeLogStatus,
    NodeLogTriggerType,
    NodeType,
)
from db.models.logs import AppLog, NodeLog
from db.models.pipelines import Node
from db.models.prompts import TaskManualRequestQueue
from services import container_monitor, server_status, volume_usage
from services.account_router import ACCOUNT_ROUTER_LOG_SOURCE, ACCOUNT_SWITCHED_MESSAGE
from services.container_monitor import (
    ContainerKind,
    list_task_containers,
    node_expired,
    parse_created_at,
)
from services.maintenance import MAINTENANCE_KEY
from services.node_stats import StatsPeriod, node_stats
from services.nodes.script import NODE_CONTAINER_PREFIX
from services.server_status import (
    Dependency,
    deployed_at_from_env,
    server_overview,
    workers_per_queue,
)
from services.session_container import SESSION_CONTAINER_PREFIX
from services.session_heartbeat import beat
from services.volume_usage import VOLUME_USAGE_KEY, Volume, directory_size, store_volume_usage
from tests.factories import make_llm_account, make_task, make_user

if TYPE_CHECKING:
    from httpx import AsyncClient
    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncSession

    from tests.cliproxy_support import FakeCliproxy

_QUEUES = ("celery", "sessions", "backups")


class _BrokenRedis:
    async def ping(self) -> None:
        raise RedisConnectionError("connection refused")


class TestServerOverviewApi:
    async def test_healthy(
        self,
        admin_client: AsyncClient,
        db_session: AsyncSession,
        redis_client: Redis,
        api_cliproxy: FakeCliproxy,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv(server_status.VERSION_ENV, "abc123")
        monkeypatch.setenv(server_status.DEPLOYED_AT_ENV, "2026-11-12T07:00:00Z")
        monkeypatch.setattr(
            "api.monitoring._inspect_active_queues",
            lambda: {
                "celery@a": [{"name": "celery"}],
                "celery@b": [{"name": "celery"}, {"name": "backups"}],
            },
        )
        await redis_client.rpush("sessions", "m1", "m2")
        await redis_client.set(MAINTENANCE_KEY, "1")
        task = await make_task(db_session)
        db_session.add_all(
            [
                TaskManualRequestQueue(
                    task_id=task.id,
                    request_type=ManualRequestType.FREEFORM_PROMPT,
                    raw_prompt_text="p",
                    requested_by=task.created_by,
                    status=status,
                )
                for status in (
                    ManualRequestStatus.QUEUED,
                    ManualRequestStatus.QUEUED,
                    ManualRequestStatus.PROCESSING,
                    ManualRequestStatus.DONE,
                )
            ],
        )
        db_session.add(
            BackupRun(
                kind=BackupRunKind.BACKUP,
                status=BackupRunStatus.SUCCESS,
                object_key="tracker/2026-11-12.tar",
            ),
        )
        await db_session.flush()

        response = await admin_client.get("/monitoring/overview")

        assert response.status_code == 200
        body = response.json()
        assert [(item["name"], item["ok"]) for item in body["dependencies"]] == [
            ("postgres", True),
            ("redis", True),
            ("llm_proxy", True),
        ]
        assert [(q["name"], q["workers"], q["pending"]) for q in body["queues"]] == [
            ("celery", 2, 0),
            ("sessions", 0, 2),
            ("backups", 1, 0),
        ]
        assert (body["manual_requests_queued"], body["manual_requests_processing"]) == (2, 1)
        assert (body["version"], body["deployed_at"]) == ("abc123", "2026-11-12T07:00:00Z")
        assert body["maintenance"] is True
        assert body["last_backup"]["object_key"] == "tracker/2026-11-12.tar"
        assert body["last_verify"] is None

    @pytest.mark.usefixtures("redis_client")
    async def test_proxy_down(
        self,
        admin_client: AsyncClient,
        api_cliproxy: FakeCliproxy,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        api_cliproxy.down = True
        monkeypatch.setattr("api.monitoring._inspect_active_queues", lambda: None)

        response = await admin_client.get("/monitoring/overview")

        [proxy] = [d for d in response.json()["dependencies"] if d["name"] == "llm_proxy"]
        assert proxy["ok"] is False
        assert proxy["error"]


class TestServerOverviewService:
    async def test_redis_down(
        self,
        db_session: AsyncSession,
        fake_cliproxy: FakeCliproxy,
    ) -> None:
        overview = await server_overview(
            db_session,
            _BrokenRedis(),  # type: ignore[arg-type]
            fake_cliproxy.client(),
            queue_names=_QUEUES,
            active_queues=None,
        )

        [redis] = [d for d in overview.dependencies if d.name is Dependency.REDIS]
        assert (redis.ok, redis.error) == (False, "ConnectionError")
        assert [queue.pending for queue in overview.queues] == [None, None, None]
        assert overview.maintenance is None

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            (None, {}),
            ({"celery@a": []}, {}),
            ({"celery@a": [{"name": "celery"}, {"name": "celery"}]}, {"celery": 1}),
            (
                {"celery@a": [{"name": "celery"}], "celery@b": [{"name": "celery"}, {}]},
                {"celery": 2},
            ),
        ],
    )
    def test_workers_per_queue(
        self,
        raw: dict[str, list[dict[str, str]]] | None,
        expected: dict[str, int],
    ) -> None:
        assert dict(workers_per_queue(raw)) == expected

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("", None),
            ("вчера", None),
            ("2026-11-12T07:00:00Z", datetime(2026, 11, 12, 7, tzinfo=UTC)),
        ],
    )
    def test_deployed_at(
        self,
        monkeypatch: pytest.MonkeyPatch,
        raw: str,
        expected: datetime | None,
    ) -> None:
        monkeypatch.setenv(server_status.DEPLOYED_AT_ENV, raw)

        assert deployed_at_from_env() == expected


class TestNodeStats:
    async def _log(
        self,
        db_session: AsyncSession,
        *,
        task_id: uuid.UUID,
        node_id: uuid.UUID | None,
        status: NodeLogStatus,
        started_at: datetime,
        duration: timedelta | None = None,
        attempt: int = 1,
        user_input: str | None = None,
    ) -> None:
        db_session.add(
            NodeLog(
                task_id=task_id,
                node_id=node_id,
                trigger_type=NodeLogTriggerType.PIPELINE,
                status=status,
                attempt_number=attempt,
                started_at=started_at,
                finished_at=started_at + duration if duration is not None else None,
                user_input_text=user_input,
            ),
        )
        await db_session.flush()

    async def _node(self, db_session: AsyncSession, name: str, author: uuid.UUID) -> Node:
        node = Node(
            name=name,
            node_type=NodeType.PLAIN_PROMPT,
            is_library_item=True,
            created_by=author,
        )
        db_session.add(node)
        await db_session.flush()
        return node

    @pytest.mark.parametrize(
        ("period", "total", "failed"),
        [(StatsPeriod.DAY, 5, 3), (StatsPeriod.WEEK, 6, 4)],
    )
    async def test_counts_and_durations(
        self,
        db_session: AsyncSession,
        period: StatsPeriod,
        total: int,
        failed: int,
    ) -> None:
        now = datetime.now(UTC)
        task = await make_task(db_session)
        build = await self._node(db_session, "Сборка", task.created_by)
        lint = await self._node(db_session, "Линт", task.created_by)
        recent = now - timedelta(hours=1)
        for node, status, duration, attempt, user_input in [
            (build, NodeLogStatus.SUCCESS, timedelta(seconds=10), 1, None),
            (build, NodeLogStatus.FAILED, timedelta(seconds=30), 2, None),
            (lint, NodeLogStatus.FAILED, None, 1, None),
            (lint, NodeLogStatus.FAILED, timedelta(hours=5), 1, "Принять план"),
            (None, NodeLogStatus.STOPPED, timedelta(seconds=20), 1, None),
        ]:
            await self._log(
                db_session,
                task_id=task.id,
                node_id=node.id if node else None,
                status=status,
                started_at=recent,
                duration=duration,
                attempt=attempt,
                user_input=user_input,
            )
        await self._log(
            db_session,
            task_id=task.id,
            node_id=build.id,
            status=NodeLogStatus.FAILED,
            started_at=now - timedelta(days=3),
        )

        stats = await node_stats(db_session, period=period, now=now)

        assert (stats.total, stats.success, stats.failed, stats.stopped, stats.retries) == (
            total,
            1,
            failed,
            1,
            1,
        )
        assert (stats.avg_duration_seconds, stats.max_duration_seconds) == (20.0, 30.0)
        # При равном числе сбоев — по имени.
        assert [(row.node_name, row.failed) for row in stats.top_failing] == (
            [("Линт", 2), ("Сборка", 1 if period is StatsPeriod.DAY else 2)]
        )

    async def test_api(self, admin_client: AsyncClient) -> None:
        response = await admin_client.get("/monitoring/node-stats", params={"period": "week"})

        assert response.status_code == 200
        assert response.json()["period"] == "week"


class TestLlmUsage:
    async def _switch(
        self,
        db_session: AsyncSession,
        *,
        to_account: uuid.UUID,
        age: timedelta,
        message: str = ACCOUNT_SWITCHED_MESSAGE,
    ) -> None:
        db_session.add(
            AppLog(
                level=AppLogLevel.INFO,
                source=ACCOUNT_ROUTER_LOG_SOURCE,
                message=message,
                context={"to_account_id": str(to_account)},
                created_at=datetime.now(UTC) - age,
            ),
        )
        await db_session.flush()

    async def test_usage_and_switches(
        self,
        admin_client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        owner = await make_user(db_session)
        main = await make_llm_account(db_session, owner_id=owner.id, label="Основной")
        spare = await make_llm_account(db_session, owner_id=owner.id, label="Запасной")
        main.usage_5h_pct, main.usage_week_pct = Decimal("42.5"), Decimal("10")
        await self._switch(db_session, to_account=spare.id, age=timedelta(hours=1))
        await self._switch(db_session, to_account=spare.id, age=timedelta(hours=2))
        await self._switch(db_session, to_account=main.id, age=timedelta(hours=3))
        await self._switch(db_session, to_account=main.id, age=timedelta(days=2))
        await self._switch(
            db_session,
            to_account=main.id,
            age=timedelta(hours=1),
            message="llm_account_checked",
        )

        response = await admin_client.get("/monitoring/llm-usage")

        assert response.status_code == 200
        body = response.json()
        assert body["switches_24h"] == 3
        rows = {row["label"]: row for row in body["accounts"] if row["owner_email"] == owner.email}
        assert (
            float(rows["Основной"]["usage_5h_pct"]),
            float(rows["Основной"]["usage_week_pct"]),
        ) == (42.5, 10)
        assert (rows["Основной"]["switches_to_24h"], rows["Запасной"]["switches_to_24h"]) == (1, 2)


class TestDiskUsage:
    def test_directory_size(self, tmp_path: Path) -> None:
        (tmp_path / "nested").mkdir()
        (tmp_path / "a.txt").write_bytes(b"x" * 10)
        (tmp_path / "nested" / "b.txt").write_bytes(b"y" * 5)
        outside = tmp_path.parent / f"outside-{uuid.uuid4().hex}"
        outside.write_bytes(b"z" * 100)
        (tmp_path / "link").symlink_to(outside)
        try:
            assert directory_size(tmp_path) == 15
            assert directory_size(tmp_path / "missing") is None
        finally:
            outside.unlink()

    async def test_measured(
        self,
        admin_client: AsyncClient,
        redis_client: Redis,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        (tmp_path / "repos").mkdir()
        (tmp_path / "repos" / "f").write_bytes(b"x" * 7)
        monkeypatch.setitem(
            volume_usage.VOLUME_ROOTS, Volume.TASK_REPOS, lambda: tmp_path / "repos"
        )
        monkeypatch.setitem(volume_usage.VOLUME_ROOTS, Volume.USER_FILES, lambda: tmp_path / "none")
        monkeypatch.setattr(volume_usage, "resolve_repos_root", lambda: tmp_path)
        now = datetime(2026, 11, 12, 7, tzinfo=UTC)
        await store_volume_usage(redis_client, now=now)

        body = (await admin_client.get("/monitoring/disk")).json()

        sizes = {row["name"]: row["size_bytes"] for row in body["volumes"]}
        assert (sizes["task_repos"], sizes["user_files"]) == (7, None)
        assert body["measured_at"] == "2026-11-12T07:00:00Z"
        assert body["database_bytes"] > 0
        assert body["free_bytes"] is not None

    @pytest.mark.parametrize("stored", [None, "{not json", '{"sizes": {}}'])
    async def test_without_measurement(
        self,
        admin_client: AsyncClient,
        redis_client: Redis,
        stored: str | None,
    ) -> None:
        if stored is not None:
            await redis_client.set(VOLUME_USAGE_KEY, stored)

        body = (await admin_client.get("/monitoring/disk")).json()

        assert (body["volumes"], body["measured_at"]) == ([], None)


class TestContainers:
    @pytest.mark.parametrize(
        ("deadline", "age", "expired"),
        [
            ("2000", timedelta(0), True),
            ("9999999999", timedelta(days=1), False),
            ("", timedelta(minutes=11), True),
            ("", timedelta(minutes=9), False),
        ],
        ids=["deadline-passed", "deadline-ahead", "no-label-old", "no-label-fresh"],
    )
    def test_node_expired(self, deadline: str, age: timedelta, expired: bool) -> None:
        now = datetime.now(UTC)

        assert (
            node_expired(
                deadline_raw=deadline,
                started_at=now - age,
                now=now,
                grace_period=timedelta(minutes=10),
            )
            is expired
        )

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("2026-11-12 10:36:23 +0300 MSK", datetime(2026, 11, 12, 7, 36, 23, tzinfo=UTC)),
            ("", None),
        ],
    )
    def test_parse_created_at(self, raw: str, expected: datetime | None) -> None:
        assert parse_created_at(raw) == expected

    async def test_listing(
        self,
        admin_client: AsyncClient,
        db_session: AsyncSession,
        redis_client: Redis,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        alive, gone = await make_task(db_session), await make_task(db_session)
        await beat(redis_client, alive.id)
        listings = {
            SESSION_CONTAINER_PREFIX: (
                f"tracker-session-a\t{alive.id}\t2026-11-12 10:00:00 +0300 MSK\n"
                f"tracker-session-b\t{gone.id}\t2026-11-12 09:00:00 +0300 MSK\n"
            ),
            NODE_CONTAINER_PREFIX: ("tracker-node-c\t2000\tRR-1\t2026-11-12 08:00:00 +0300 MSK\n"),
        }

        async def fake_docker(*args: str) -> str:
            prefix = args[args.index("--filter") + 1].removeprefix("name=")
            return listings[prefix]

        monkeypatch.setattr(container_monitor, "run_docker", fake_docker)

        response = await admin_client.get("/monitoring/containers")

        assert response.status_code == 200
        assert [
            (row["name"], row["kind"], row["task_code"], row["orphaned"]) for row in response.json()
        ] == [
            ("tracker-node-c", ContainerKind.NODE, "RR-1", True),
            ("tracker-session-b", ContainerKind.SESSION, gone.code, True),
            ("tracker-session-a", ContainerKind.SESSION, alive.code, False),
        ]

    async def test_session_without_label_kept(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        async def fake_docker(*args: str) -> str:
            if SESSION_CONTAINER_PREFIX in args[2]:
                return "tracker-session-x\t\t2026-11-12 10:00:00 +0300 MSK\n"
            return ""

        monkeypatch.setattr(container_monitor, "run_docker", fake_docker)

        [container] = await list_task_containers(db_session, redis_client, now=datetime.now(UTC))

        assert (container.task_id, container.orphaned) == (None, False)


@pytest.mark.parametrize(
    "path",
    [
        "/monitoring/overview",
        "/monitoring/node-stats",
        "/monitoring/llm-usage",
        "/monitoring/disk",
        "/monitoring/containers",
    ],
)
async def test_admin_only(authed_client: AsyncClient, path: str) -> None:
    response = await authed_client.get(path)

    assert response.status_code == 403
