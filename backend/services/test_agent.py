"""Встроенные инструменты проверок и отдельные CI-агенты Luna."""

from __future__ import annotations

import asyncio
import contextlib
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from claude_agent_sdk import create_sdk_mcp_server, tool
from claude_agent_sdk.types import McpSdkServerConfig
from sqlalchemy.ext.asyncio import AsyncSession

from api.schemas.test_runs import TestRunResponse
from app_logging.config import get_logger
from clients.claude_agent import TrackerSdkClient, build_claude_agent_options
from clients.cliproxy import open_cliproxy_client
from db.models.enums import LlmAccountStatus, NodeLogStatus, ReasoningEffort
from db.models.llm import LlmAccount
from db.models.logs import NodeLog
from db.models.repositories import Repository
from db.models.tasks import Task, TaskRepository
from db.models.test_runs import TestRun
from db.models.users import User
from db.session import async_session_factory
from services.account_router import ROUTE_LOCK_KEY, ROUTE_LOCK_TTL_SECONDS
from services.ci_turn_gate import (
    CI_GATE_POLL_SECONDS,
    CI_GATE_READY,
    CI_KEY_TTL_SECONDS,
    CI_REPLY_KEY,
    gate_key,
    request_key,
    reservation_key,
    reservations,
)
from services.claude_config import session_config_dir
from services.distributed_lock import acquire_lock
from services.errors import AppError, ConflictError, NotFoundError, ValidationError
from services.llm_account_choice import AccountView, LimitState, limit_state
from services.llm_accounts import account_models
from services.llm_routing import TurnRoute, llm_session_token, publish_route
from services.llm_usage import refresh_account_usage
from services.redis_connection import redis_connection
from services.session_container import build_session_cli_env
from services.system_settings import get_llm_week_threshold
from services.task_artifacts import task_artifacts_dir
from services.task_workspace import task_repos_path
from services.test_runs import (
    ACTIVE_STATUSES,
    cancelled,
    cleanup_run,
    create_run,
    execute_run,
    update_run,
)

logger = get_logger("test_agent")

LUNA_MODEL = "gpt-6-luna"
CI_AGENT_MAX_TURNS = 4
CI_AGENT_HEARTBEAT_SECONDS = 5
CI_AGENT_SHUTDOWN_TIMEOUT_SECONDS = 120
CI_CHECKS = ("unit", "integration")
SESSION_CLI_PATH = Path(__file__).resolve().parents[1] / "session_cli.py"


def response(payload: Any, *, error: bool = False) -> dict[str, Any]:
    return {
        "is_error": error,
        "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False, default=str)}],
    }


async def build_test_tools(task: Task) -> McpSdkServerConfig:
    task_id = task.id

    async def handle(name: str, args: dict[str, Any]) -> dict[str, Any]:
        from tasks.test_runs import execute_test_run

        try:
            async with async_session_factory() as db:
                current = await db.get(Task, task_id)
                if current is None:
                    raise NotFoundError("Задача не найдена")
                if name == "profiles":
                    repositories = list(
                        (
                            await db.scalars(
                                sa.select(Repository)
                                .join(
                                    TaskRepository,
                                    TaskRepository.repository_id == Repository.id,
                                )
                                .where(TaskRepository.task_id == task_id)
                            )
                        ).all()
                    )
                    return response(
                        [
                            {
                                "repository_id": r.id,
                                "name": r.name,
                                "checks": list((r.test_profile or {}).get("commands", {})),
                            }
                            for r in repositories
                            if r.test_profile
                        ]
                    )
                if name in ("run_check", "run_ci"):
                    repository_id = uuid.UUID(args["repository_id"])
                    key = uuid.UUID(args["idempotency_key"])
                    if name == "run_ci":
                        return response(
                            await create_ci_runs(
                                db,
                                task=current,
                                repository_id=repository_id,
                                key=key,
                            )
                        )
                    run = await create_run(
                        db,
                        task=current,
                        repository_id=repository_id,
                        check=args["check"],
                        source="agent",
                        idempotency_key=key,
                    )
                    execute_test_run.delay(str(run.id))
                else:
                    found = await db.get(TestRun, uuid.UUID(args["run_id"]))
                    if found is None:
                        raise NotFoundError("Прогон не найден")
                    run = found
                    if run.task_id != task_id:
                        raise NotFoundError("Прогон не найден")
                    if name == "stop_check" and run.status in ACTIVE_STATUSES:
                        run.cancel_requested = True
                        await db.commit()
                return response(TestRunResponse.model_validate(run).model_dump(mode="json"))
        except (AppError, ValueError, KeyError) as exc:
            return response(str(exc), error=True)

    definitions: list[tuple[str, str, dict[str, type[str]]]] = [
        ("profiles", "Список репозиториев задачи и доступных проверок.", {}),
        (
            "run_check",
            "Запустить проверку. Передай новый UUID idempotency_key; повтори его при retry.",
            {"repository_id": str, "check": str, "idempotency_key": str},
        ),
        (
            "run_ci",
            "Запустить двух агентов gpt-6-luna параллельно: unit+lint и integration. "
            "Возвращает ID прогонов. Дождись их результатов и cleanup_status=done.",
            {"repository_id": str, "idempotency_key": str},
        ),
        ("get_check_result", "Результат, логи, отчёты и состояние очистки.", {"run_id": str}),
        ("stop_check", "Остановить проверку и очистить окружение.", {"run_id": str}),
    ]
    tools = []
    for name, description, schema in definitions:

        async def handler(args: dict[str, Any], method: str = name) -> dict[str, Any]:
            return await handle(method, args)

        tools.append(tool(name, description, schema)(handler))
    return create_sdk_mcp_server(name="tracker-tests", tools=tools)


async def luna_route(owner_id: uuid.UUID, *, run_id: uuid.UUID | None = None) -> TurnRoute:
    async with async_session_factory() as db, open_cliproxy_client() as proxy:
        accounts = list(
            (
                await db.scalars(
                    sa.select(LlmAccount)
                    .where(
                        LlmAccount.created_by == owner_id,
                        LlmAccount.provider == "openai",
                        LlmAccount.status.in_(
                            (LlmAccountStatus.ACTIVE, LlmAccountStatus.RATE_LIMITED)
                        ),
                    )
                    .order_by(LlmAccount.switch_order, LlmAccount.id)
                )
            ).all()
        )
        async with redis_connection() as redis:
            ci_turns = await reservations(redis, owner_id, exclude=run_id)
        running = dict(
            (
                await db.execute(
                    sa.select(
                        NodeLog.llm_account_id,
                        sa.func.count(NodeLog.id),
                    )
                    .where(
                        NodeLog.status == NodeLogStatus.RUNNING,
                        NodeLog.llm_account_id.in_([account.id for account in accounts]),
                    )
                    .group_by(NodeLog.llm_account_id)
                )
            ).all()
        )
        owner = await db.get(User, owner_id)
        if owner is None:
            raise NotFoundError("Автор задачи не найден")
        credentials = await proxy.list_credentials()
        week_threshold = await get_llm_week_threshold(db)
        for account in accounts:
            credential = next(
                (item for item in credentials if item.name == account.cliproxy_credential),
                None,
            )
            if credential is not None:
                await refresh_account_usage(
                    proxy,
                    account,
                    auth_index=credential.auth_index,
                    now=datetime.now(UTC),
                )
                await db.commit()
            state = limit_state(
                AccountView(
                    account, running_turns=running.get(account.id, 0) + ci_turns.get(account.id, 0)
                ),
                threshold_pct=owner.llm_switch_threshold_5h_pct,
                week_threshold_pct=week_threshold,
                now=datetime.now(UTC),
            )
            if state.state not in (LimitState.FREE, LimitState.RUNNING):
                continue
            if LUNA_MODEL in await account_models(proxy, account):
                return TurnRoute(
                    account_id=account.id,
                    prefix=account.cliproxy_prefix,
                    model=LUNA_MODEL,
                    effort=ReasoningEffort.LOW,
                    provider_effort=ReasoningEffort.LOW,
                )
    raise ValidationError(
        "Для CI-агентов нужен OpenAI-аккаунт с моделью gpt-6-luna и доступным лимитом"
    )


async def create_ci_runs(
    db: AsyncSession,
    *,
    task: Task,
    repository_id: uuid.UUID,
    key: uuid.UUID,
) -> list[dict[str, Any]]:
    from tasks.test_runs import execute_test_run

    await db.execute(sa.select(Task.id).where(Task.id == task.id).with_for_update())
    keys = [uuid.uuid5(key, check) for check in CI_CHECKS]
    existing = list(
        (
            await db.scalars(
                sa.select(TestRun).where(
                    TestRun.task_id == task.id,
                    TestRun.idempotency_key.in_(keys),
                )
            )
        ).all()
    )
    for run in existing:
        expected = "unit" if run.idempotency_key == keys[0] else "integration"
        if run.repository_id != repository_id or run.check != expected or run.source != "ci-agent":
            raise ConflictError("Ключ CI уже используется другой операцией")
    if len(existing) == 2:
        await db.commit()
        for run in existing:
            if run.status == "queued":
                execute_test_run.delay(str(run.id))
        return [
            TestRunResponse.model_validate(run).model_dump(mode="json")
            for run in sorted(existing, key=lambda item: item.check == "integration")
        ]
    snapshot = existing[0].profile if existing else None
    if not existing:
        await luna_route(task.created_by)
    repository = await db.scalar(
        sa.select(Repository)
        .join(
            TaskRepository,
            TaskRepository.repository_id == Repository.id,
        )
        .where(Repository.id == repository_id, TaskRepository.task_id == task.id)
    )
    if repository is None or (snapshot is None and repository.test_profile is None):
        raise ValidationError("У репозитория задачи отсутствует тестовый профиль")
    profile = snapshot or repository.test_profile
    assert profile is not None
    commands = profile["commands"]
    if not all(name in commands for name in ("unit", "lint", "integration")):
        raise ValidationError("Для CI задайте проверки unit, lint и integration")
    results: list[dict[str, Any]] = []
    for check in CI_CHECKS:
        run = await create_run(
            db,
            task=task,
            repository_id=repository_id,
            check=check,
            source="ci-agent",
            idempotency_key=uuid.uuid5(key, check),
            commit=False,
            profile_snapshot=snapshot,
        )
        results.append(TestRunResponse.model_validate(run).model_dump(mode="json"))
    await db.commit()
    for result in results:
        execute_test_run.delay(str(result["id"]))
    return results


async def execute_ci_agent(run_id: uuid.UUID) -> None:
    async with async_session_factory() as db:
        run = (
            await db.execute(
                sa.update(TestRun)
                .where(
                    TestRun.id == run_id,
                    TestRun.status == "queued",
                )
                .values(
                    status="agent",
                    heartbeat_at=datetime.now(UTC),
                    started_at=datetime.now(UTC),
                )
                .returning(TestRun)
            )
        ).scalar_one_or_none()
        await db.commit()
        if run is None:
            return
        task = await db.get(Task, run.task_id)
        assert task is not None
    if await cancelled(run_id):
        await update_run(run_id, status="cancelled", finished_at=datetime.now(UTC))
        await cleanup_run(run_id)
        return
    config = session_config_dir(task.code) / "test-agents" / str(run_id)
    config.mkdir(parents=True, exist_ok=True)
    client = None
    invoked = False
    monitor = None

    async def monitor_agent() -> None:
        async with redis_connection() as redis:
            next_heartbeat = 0.0
            while True:
                now = asyncio.get_running_loop().time()
                if now >= next_heartbeat:
                    await update_run(run_id, heartbeat_at=datetime.now(UTC))
                    await redis.expire(reservation_key(task.created_by, run_id), 120)
                    next_heartbeat = now + CI_AGENT_HEARTBEAT_SECONDS
                queued = await redis.blpop(request_key(run_id), timeout=CI_GATE_POLL_SECONDS)
                if queued:
                    nonce = queued[1]
                    nonce = nonce.decode() if isinstance(nonce, bytes) else nonce
                    reply = CI_REPLY_KEY.format(nonce=nonce)
                    try:
                        async with acquire_lock(
                            redis,
                            ROUTE_LOCK_KEY.format(user_id=task.created_by),
                            ttl_seconds=ROUTE_LOCK_TTL_SECONDS,
                            busy_message="Выбор LLM-аккаунта занят",
                        ):
                            selected = await luna_route(task.created_by, run_id=run_id)
                            await redis.set(
                                reservation_key(task.created_by, run_id),
                                str(selected.account_id),
                                ex=CI_KEY_TTL_SECONDS,
                            )
                            await publish_route(redis, run_id, selected)
                        message = CI_GATE_READY
                    except Exception as exc:
                        message = str(exc)
                    await redis.rpush(reply, message)
                    await redis.expire(reply, CI_KEY_TTL_SECONDS)
                if await cancelled(run_id) and client is not None:
                    await client.interrupt()
                    return

    try:
        route = await luna_route(task.created_by)

        @tool("execute", "Выполнить назначенную проверку и очистку. Вызвать ровно один раз.", {})
        async def execute(_args: dict[str, Any]) -> dict[str, Any]:
            nonlocal invoked
            if invoked:
                return response("Проверка уже выполнена", error=True)
            invoked = True
            await execute_run(run_id)
            async with async_session_factory() as db:
                result = await db.get(TestRun, run_id)
                return response(TestRunResponse.model_validate(result).model_dump(mode="json"))

        async with redis_connection() as redis, llm_session_token(redis, run_id) as token:
            await publish_route(redis, run_id, route)
            await redis.set(gate_key(run_id), "1")
            monitor = asyncio.create_task(monitor_agent())
            cli_env = await build_session_cli_env(
                task_id=task.id,
                cwd=Path(task_repos_path(task)),
                config_dir=config,
                session_token=token,
                artifacts_dir=task_artifacts_dir(task.code),
            )
            spec = json.loads(cli_env["TRACKER_SESSION_DOCKER_SPEC"])
            spec["docker_args"].extend(["--label", f"tracker.test_agent={run_id}"])
            cli_env["TRACKER_SESSION_DOCKER_SPEC"] = json.dumps(spec)
            options = build_claude_agent_options(
                resume_session_id=None,
                cwd=task_repos_path(task),
                permission_mode="bypassPermissions",
                mcp_servers={
                    "tracker-tests": create_sdk_mcp_server(
                        name="tracker-tests",
                        tools=[execute],
                    )
                },
                claude_config_dir=str(config),
                enable_remote_control=False,
                cli_path=str(SESSION_CLI_PATH),
                cli_env=cli_env,
            )
            options.tools = []
            options.allowed_tools = ["mcp__tracker-tests__execute"]
            options.max_turns = CI_AGENT_MAX_TURNS
            client = TrackerSdkClient(options=options)
            async with asyncio.timeout(
                run.profile["timeout_seconds"] + CI_AGENT_SHUTDOWN_TIMEOUT_SECONDS
            ):
                await client.connect()
                await client.query(
                    "Ты CI-агент. Вызови mcp__tracker-tests__execute для назначенной проверки. "
                    "После получения результата кратко сообщи итог на русском. "
                    "Используй только этот инструмент. Код и файлы не изменяй.",
                )
                async for _message in client.receive_response():
                    if await cancelled(run_id):
                        await client.interrupt()
                        break
            if not invoked:
                raise ConflictError("CI-агент завершился без запуска назначенной проверки")
    except Exception as exc:
        async with async_session_factory() as db:
            current = await db.get(TestRun, run_id)
        if current is not None and current.status in ACTIVE_STATUSES:
            await update_run(
                run_id,
                status="cancelled" if current.cancel_requested else "failed",
                error=str(exc),
                finished_at=datetime.now(UTC),
            )
    finally:
        if monitor is not None:
            monitor.cancel()
            try:
                await monitor
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.exception("ci_agent_monitor_failed", run_id=str(run_id))
        if client is not None:
            with contextlib.suppress(Exception):
                await client.disconnect()
        async with redis_connection() as redis:
            await redis.delete(
                gate_key(run_id), request_key(run_id), reservation_key(task.created_by, run_id)
            )
        with contextlib.suppress(RuntimeError, OSError, TimeoutError):
            await cleanup_run(run_id)
