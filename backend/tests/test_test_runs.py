"""
Контракты профиля, повторные запросы и изоляция Compose-прогонов.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from claude_agent_sdk import create_sdk_mcp_server

from api.schemas.test_runs import TestProfile as Profile
from db.models.enums import RepositoryRole
from db.models.repositories import Repository
from db.models.tasks import Task, TaskRepository
from db.models.test_runs import TestRun
from services import test_agent, test_runs
from services.ci_turn_gate import reservation_key, reservations
from services.errors import ConflictError, ValidationError
from services.test_profile import detect_directory
from tests.factories import make_task
from tests.test_plan_mode import _non_closing_session_factory

if TYPE_CHECKING:
    from httpx import AsyncClient
    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncSession

    from db.models.users import User


@pytest.fixture
async def configured_task(
    db_session: AsyncSession,
    current_user: User,
) -> tuple[Task, Repository]:
    repository = Repository(
        name=f"checks-{uuid.uuid4().hex[:8]}",
        git_url="https://example.com/checks.git",
        test_profile=Profile(commands={"unit": "sh scripts/unit.sh"}).model_dump(),
    )
    db_session.add(repository)
    await db_session.flush()
    task = await make_task(db_session, created_by=current_user.id)
    db_session.add(
        TaskRepository(
            task_id=task.id,
            repository_id=repository.id,
            role=RepositoryRole.READ_WRITE,
            branch_name="checks",
            base_branch="main",
        )
    )
    await db_session.commit()
    return task, repository


class TestManualRuns:
    async def test_manual_retry_preserves_run(
        self,
        configured_task: tuple[Task, Repository],
        authed_client: AsyncClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr("api.tasks.test_runs.execute_test_run.delay", lambda _: None)
        task, repository = configured_task
        body = {
            "repository_id": str(repository.id),
            "check": "unit",
            "idempotency_key": str(uuid.uuid4()),
        }
        first = await authed_client.post(f"/tasks/{task.id}/test-runs", json=body)
        second = await authed_client.post(f"/tasks/{task.id}/test-runs", json=body)
        assert first.status_code == second.status_code == 201
        assert first.json()["id"] == second.json()["id"]
        runs = await authed_client.get(f"/tasks/{task.id}/test-runs")
        assert len(runs.json()) == 1
        body["check"] = "integration"
        conflict = await authed_client.post(f"/tasks/{task.id}/test-runs", json=body)
        assert conflict.status_code == 409

    async def test_stop_requests_cancellation(
        self,
        configured_task: tuple[Task, Repository],
        authed_client: AsyncClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr("api.tasks.test_runs.execute_test_run.delay", lambda _: None)
        task, repository = configured_task
        created = await authed_client.post(
            f"/tasks/{task.id}/test-runs",
            json={
                "repository_id": str(repository.id),
                "check": "unit",
            },
        )
        path = f"/tasks/{task.id}/test-runs/{created.json()['id']}"
        assert (await authed_client.post(path + "/stop")).status_code == 200
        assert (await authed_client.post(path + "/cleanup")).status_code == 409

    async def test_foreign_task_hidden(
        self,
        configured_task: tuple[Task, Repository],
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        foreign = await make_task(db_session)
        await db_session.commit()
        result = await authed_client.get(f"/tasks/{foreign.id}/test-runs")
        assert result.status_code == 404

    async def test_unlinked_repository_rejected(
        self,
        configured_task: tuple[Task, Repository],
        authed_client: AsyncClient,
    ) -> None:
        task, _ = configured_task
        result = await authed_client.post(
            f"/tasks/{task.id}/test-runs",
            json={
                "repository_id": str(uuid.uuid4()),
                "check": "unit",
            },
        )
        assert result.status_code == 404

    async def test_idempotency_conflict(
        self,
        configured_task: tuple[Task, Repository],
        db_session: AsyncSession,
    ) -> None:
        task, repository = configured_task
        key = uuid.uuid4()
        await test_runs.create_run(
            db_session,
            task=task,
            repository_id=repository.id,
            check="unit",
            source="manual",
            idempotency_key=key,
        )
        with pytest.raises(ConflictError):
            await test_runs.create_run(
                db_session,
                task=task,
                repository_id=uuid.uuid4(),
                check="unit",
                source="manual",
                idempotency_key=key,
            )


class TestProfiles:
    @pytest.mark.parametrize("filename", ["../compose.yml", "/etc/compose.yml"])
    def test_profile_paths_stay_inside_repository(self, filename: str) -> None:
        with pytest.raises(ValueError):
            Profile(compose_files=[filename])

    def test_detect_uses_project_commands(self, tmp_path: Path) -> None:
        (tmp_path / "compose.yml").write_text("services:\n  app:\n    image: example\n")
        (tmp_path / "scripts").mkdir()
        (tmp_path / "scripts/unittests.sh").write_text("echo test")
        profile = detect_directory(tmp_path)
        assert profile.commands == {"unit": "sh /app/scripts/unittests.sh"}
        assert profile.compose_files == ["compose.yml"]
        assert profile.service == "app"


class TestComposeIsolation:
    async def test_compose_resources_are_isolated(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        async def mount(_root: Path) -> None:
            return None

        monkeypatch.setattr(test_runs, "resolve_root_mount", mount)
        run_id = uuid.uuid4()
        result = await test_runs.isolated_config(
            {
                "services": {
                    "app": {
                        "image": "app",
                        "ports": ["8000:8000"],
                        "container_name": "shared",
                        "volumes": [
                            {"type": "bind", "source": str(tmp_path / "tmp"), "target": "/data"}
                        ],
                    },
                    "db": {
                        "image": "postgres:16",
                        "volumes": [{"type": "volume", "source": "database", "target": "/data"}],
                    },
                },
                "volumes": {"database": {"name": "shared-database"}},
                "networks": {"default": {"name": "shared-network"}},
            },
            snapshot=tmp_path,
            run_id=run_id,
        )
        assert "ports" not in result["services"]["app"]
        assert "container_name" not in result["services"]["app"]
        assert result["volumes"]["database"]["name"].startswith(test_runs.project_name(run_id))
        assert result["networks"]["default"]["name"].startswith(test_runs.project_name(run_id))
        assert "healthcheck" in result["services"]["db"]
        assert result["services"]["app"]["labels"]["tracker.test_run"] == str(run_id)

    @pytest.mark.parametrize("resource", ["volumes", "networks"])
    async def test_external_resources_rejected(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        resource: str,
    ) -> None:
        async def mount(_root: Path) -> None:
            return None

        monkeypatch.setattr(test_runs, "resolve_root_mount", mount)
        with pytest.raises(ValidationError):
            await test_runs.isolated_config(
                {"services": {"app": {}}, resource: {"shared": {"external": True}}},
                snapshot=tmp_path,
                run_id=uuid.uuid4(),
            )

    async def test_snapshot_mount_cannot_escape(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        async def mount(_root: Path) -> None:
            return None

        monkeypatch.setattr(test_runs, "resolve_root_mount", mount)
        with pytest.raises(ValidationError):
            await test_runs.isolated_config(
                {
                    "services": {
                        "app": {
                            "volumes": [
                                {
                                    "type": "bind",
                                    "source": "/var/run/docker.sock",
                                    "target": "/socket",
                                },
                            ]
                        }
                    },
                },
                snapshot=tmp_path,
                run_id=uuid.uuid4(),
            )

    @pytest.mark.parametrize(
        "field,value",
        [
            ("volumes_from", ["container:foreign"]),
            ("pid", "host"),
            ("ipc", "host"),
            ("cap_add", ["SYS_ADMIN"]),
            ("use_api_socket", True),
        ],
    )
    async def test_compose_cannot_inherit_host_access(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        field: str,
        value: Any,
    ) -> None:
        async def mount(_root: Path) -> None:
            return None

        monkeypatch.setattr(test_runs, "resolve_root_mount", mount)
        with pytest.raises(ValidationError):
            await test_runs.isolated_config(
                {"services": {"app": {"image": "redis:8-alpine", field: value}}},
                snapshot=tmp_path,
                run_id=uuid.uuid4(),
            )

    async def test_compose_keeps_resource_limits(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def mount(_root: Path) -> None:
            return None

        monkeypatch.setattr(test_runs, "resolve_root_mount", mount)
        resources = {"limits": {"cpus": "1", "memory": "512M"}}
        config = await test_runs.isolated_config(
            {
                "services": {"app": {"deploy": {"resources": resources, "replicas": 10}}},
            },
            snapshot=tmp_path,
            run_id=uuid.uuid4(),
        )
        assert config["services"]["app"]["deploy"] == {"resources": resources}

    async def test_prepare_preserves_compose_dollar_escaping(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:

        directory = tmp_path / "task" / ".tracker-test-runs" / str(uuid.uuid4())
        directory.mkdir(parents=True)
        repo = tmp_path / "task" / "repo"
        (repo / ".git").mkdir(parents=True)
        (repo / "compose.yml").write_text("services: {}")
        run = TestRun(
            id=uuid.uuid4(),
            repository_name="repo",
            logs="",
            profile=Profile(commands={"unit": "true"}).model_dump(),
        )
        executor = test_runs.ComposeExecutor(run, directory)
        original = ["sh", "-c", "echo $$HOSTNAME"]

        async def command(args: list[str], *, capture: bool = False) -> str:
            if capture:
                return json.dumps(
                    {"services": {"app": {"image": "redis:8-alpine", "command": original}}}
                )
            return ""

        async def mount(_root: Path) -> None:
            return None

        monkeypatch.setattr(executor, "command", command)
        monkeypatch.setattr(test_runs, "resolve_root_mount", mount)
        await test_runs.prepare(executor)
        manifest = json.loads((directory / "compose.json").read_text())
        assert manifest["services"]["app"]["command"] == original


class TestAgentChecks:
    async def test_mcp_scopes_runs_to_task(
        self,
        configured_task: tuple[Task, Repository],
        db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:

        task, repository = configured_task
        tools: dict[str, Any] = {}

        def capture(**kwargs: Any) -> Any:
            tools.update({item.name: item for item in kwargs["tools"]})
            return create_sdk_mcp_server(**kwargs)

        monkeypatch.setattr(test_agent, "create_sdk_mcp_server", capture)
        monkeypatch.setattr(
            test_agent,
            "async_session_factory",
            _non_closing_session_factory(db_session),
        )
        monkeypatch.setattr("tasks.test_runs.execute_test_run.delay", lambda _: None)
        await test_agent.build_test_tools(task)
        result = await tools["run_check"].handler(
            {
                "repository_id": str(repository.id),
                "check": "unit",
                "idempotency_key": str(uuid.uuid4()),
            }
        )
        assert not result.get("is_error"), result
        run_id = json.loads(result["content"][0]["text"])["id"]
        other = await make_task(db_session)
        await db_session.commit()
        await test_agent.build_test_tools(other)
        result = await tools["get_check_result"].handler({"run_id": run_id})
        assert result["is_error"]

    async def test_ci_checks_are_split_and_idempotent(
        self,
        configured_task: tuple[Task, Repository],
        db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:

        task, repository = configured_task
        repository.test_profile = Profile(
            commands={
                "unit": "sh unit.sh",
                "lint": "sh lint.sh",
                "integration": "sh integration.sh",
            }
        ).model_dump()
        await db_session.commit()

        async def route(_owner_id: uuid.UUID) -> None:
            return None

        monkeypatch.setattr(test_agent, "ci_agent_route", route)
        monkeypatch.setattr("tasks.test_runs.execute_test_run.delay", lambda _: None)
        key = uuid.uuid4()
        runs = await test_agent.create_ci_runs(
            db_session,
            task=task,
            repository_id=repository.id,
            key=key,
        )
        repeated = await test_agent.create_ci_runs(
            db_session,
            task=task,
            repository_id=repository.id,
            key=key,
        )
        assert [run["id"] for run in runs] == [run["id"] for run in repeated]
        assert {run["check"] for run in runs} == {"unit", "integration"}
        assert len({run["id"] for run in runs}) == 2

    async def test_ci_retry_uses_saved_profile_without_model_probe(
        self,
        configured_task: tuple[Task, Repository],
        db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:

        task, repository = configured_task
        repository.test_profile = Profile(
            commands={
                "unit": "echo unit",
                "lint": "echo lint",
                "integration": "echo integration",
            }
        ).model_dump()
        await db_session.commit()

        async def available(_owner: uuid.UUID) -> None:
            return None

        monkeypatch.setattr(test_agent, "ci_agent_route", available)
        monkeypatch.setattr("tasks.test_runs.execute_test_run.delay", lambda _: None)
        key = uuid.uuid4()
        first = await test_agent.create_ci_runs(
            db_session,
            task=task,
            repository_id=repository.id,
            key=key,
        )

        async def unavailable(_owner: uuid.UUID) -> None:
            raise ValidationError("Лимит исчерпан")

        monkeypatch.setattr(test_agent, "ci_agent_route", unavailable)
        repository.test_profile = None
        await db_session.commit()
        second = await test_agent.create_ci_runs(
            db_session,
            task=task,
            repository_id=repository.id,
            key=key,
        )
        assert {r["id"] for r in first} == {r["id"] for r in second}

    async def test_ci_reservations_exclude_current_agent(self, redis_client: Redis) -> None:

        owner, run, other, account = (uuid.uuid4() for _ in range(4))
        keys = [reservation_key(owner, run), reservation_key(owner, other)]
        try:
            for key in keys:
                await redis_client.set(key, str(account), ex=120)
            assert await reservations(redis_client, owner) == {account: 2}
            assert await reservations(redis_client, owner, exclude=run) == {account: 1}
        finally:
            await redis_client.delete(*keys)


class TestRunCleanup:
    async def test_report_transport_error_is_not_missing_file(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:

        run = TestRun(id=uuid.uuid4(), profile={"report_paths": ["report.xml"]})
        task = Task(code="RR-REPORT")
        monkeypatch.setattr(test_runs, "task_artifacts_dir", lambda _: tmp_path / "artifacts")

        async def docker(*args: str) -> str:
            if args[0] == "inspect":
                return "/app"
            raise RuntimeError("Docker transport connection lost")

        monkeypatch.setattr(test_runs, "docker_command", docker)
        with pytest.raises(OSError, match="report.xml"):
            await test_runs.save_reports(run, task, tmp_path / "run")

    async def test_cleanup_removes_crashed_agent_directory(
        self,
        configured_task: tuple[Task, Repository],
        db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:

        task, repository = configured_task
        run = await test_runs.create_run(
            db_session,
            task=task,
            repository_id=repository.id,
            check="unit",
            source="manual",
            idempotency_key=uuid.uuid4(),
        )
        run.status = "passed"
        await db_session.commit()
        monkeypatch.setenv("CLAUDE_SESSIONS_ROOT", str(tmp_path / "sessions"))
        monkeypatch.setenv("TRACKER_REPOS_ROOT", str(tmp_path / "repos"))
        directory = tmp_path / "sessions" / task.code / "test-agents" / str(run.id)
        directory.mkdir(parents=True)
        (directory / "history").write_text("session")
        monkeypatch.setattr(
            test_runs, "async_session_factory", _non_closing_session_factory(db_session)
        )

        async def docker(*args: str) -> str:
            return ""

        monkeypatch.setattr(test_runs, "docker_command", docker)
        await test_runs.cleanup_run(run.id)
        assert not directory.exists()
        await db_session.refresh(run)
        assert run.cleanup_status == "done"

    async def test_recovery_continues_after_resource_disappears(
        self,
        db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:

        calls: list[tuple[str, ...]] = []

        async def docker(*args: str) -> str:
            calls.append(args)
            if args[0] == "inspect":
                raise RuntimeError("No such object")
            return "gone" if args[0] == "ps" else ""

        monkeypatch.setattr(test_runs, "docker_command", docker)
        monkeypatch.setattr(
            test_runs, "async_session_factory", _non_closing_session_factory(db_session)
        )
        await test_runs.recover_runs()
        assert any(call[0] == "image" for call in calls)
