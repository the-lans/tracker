"""
E2E полного цикла задачи (раздел 21.1 ТЗ, решение 2026-10-20: уровень backend).

Создание задачи → отключение части нод → автозапуск по расписанию →
прохождение включённых нод, включая `plan_prompt` с решением пользователя →
запуск и остановка системного промта из библиотеки → свободный промт →
`done` с запушенной веткой.

Пользователь действует через настоящий HTTP API, задачу выполняет настоящий
воркер сессии; подменён только Claude Agent SDK (`FakeClaudeAgentClient`):
настоящий Claude в CI недоступен. Действия «пользователя» во время хода
выполняются из хуков фейка — так же, как в `test_session_worker.py`.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import pytest
import sqlalchemy as sa
from claude_agent_sdk.types import ToolPermissionContext

from db.models.enums import (
    LibraryPromptRunStatus,
    ManualRequestStatus,
    NodeLogStatus,
    NodeLogTriggerType,
    NodeType,
    TaskStatus,
)
from db.models.logs import NodeLog
from db.models.pipelines import Node, Pipeline
from db.models.repositories import Repository
from db.models.tasks import Task
from db.models.users import User
from services.autostart import run_scheduled_autostart_check
from services.crypto import encrypt
from services.plan_mode import PlanDecisionOption
from tasks import session_worker
from tests.factories import make_llm_account
from tests.fakes import FakeClaudeAgentClient, make_result_message
from tests.worker_support import init_bare_origin, run_command

if TYPE_CHECKING:
    from pathlib import Path

    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession

    from tests.worker_support import WorkerEnv

_PREPARE_PROMPT = "Подготовь окружение задачи {{task.code}}"
_LIBRARY_PROMPT = "Проверь стиль кода"
_FREEFORM_PROMPT = "Код задачи: {{task.code}}"
_PLAN_PROMPT = "Составь план"
_PLAN_TEXT = "1. Реализовать авторизацию"
_IMPLEMENT_PROMPT = "Реализуй: {{node.plan_text}}"
# Ход промта библиотеки «зависает», пока пользователь не нажмёт ■.
_HANGING_TURN_DELAY_SECONDS = 30
_STOP_PRESS_DELAY_SECONDS = 0.3


async def _make_pipeline(
    db_session: AsyncSession,
    owner_id: uuid.UUID,
) -> tuple[Pipeline, dict[str, Node]]:
    pipeline = Pipeline(name=f"e2e-{uuid.uuid4().hex[:6]}", is_archived=False, created_by=owner_id)
    db_session.add(pipeline)
    await db_session.flush()
    specs = [
        ("prepare", NodeType.PLAIN_PROMPT, _PREPARE_PROMPT),
        ("optional", NodeType.PLAIN_PROMPT, "Необязательный шаг"),
        ("plan", NodeType.PLAN_PROMPT, _PLAN_PROMPT),
        ("implement", NodeType.PLAIN_PROMPT, _IMPLEMENT_PROMPT),
    ]
    nodes = {
        name: Node(
            created_by=owner_id,
            pipeline_id=pipeline.id,
            order_index=order_index,
            name=name,
            node_type=node_type,
            prompt_template=template,
            timeout_seconds=60,
            max_retries=1,
            retry_base_delay_seconds=0,
            is_skipped=False,
            is_library_item=False,
            is_archived=False,
        )
        for order_index, (name, node_type, template) in enumerate(specs)
    }
    db_session.add_all(nodes.values())
    await db_session.flush()
    return pipeline, nodes


async def _make_library_node(db_session: AsyncSession, owner_id: uuid.UUID) -> Node:
    node = Node(
        created_by=owner_id,
        name="Стиль кода",
        description="Проверка стиля",
        node_type=NodeType.PLAIN_PROMPT,
        prompt_template=_LIBRARY_PROMPT,
        timeout_seconds=60,
        is_library_item=True,
    )
    db_session.add(node)
    await db_session.flush()
    return node


async def _make_repository(db_session: AsyncSession, origin: Path) -> Repository:
    repository = Repository(
        name="backend",
        git_url=str(origin),
        deploy_key_encrypted=encrypt("не используется файловым transport'ом"),
    )
    db_session.add(repository)
    await db_session.flush()
    return repository


class _User:
    """Действия пользователя через HTTP API во время прогона."""

    def __init__(self, client: AsyncClient, task_id: str) -> None:
        self._client = client
        self.task_id = task_id
        self.statuses_at_plan_decision: list[str] = []

    async def post(self, path: str, body: dict[str, Any] | None = None) -> Any:
        response = await self._client.post(f"/tasks/{self.task_id}{path}", json=body)
        assert response.status_code in (200, 201, 202, 204), response.text
        return response.json() if response.content else None

    async def get(self, path: str) -> Any:
        response = await self._client.get(f"/tasks/{self.task_id}{path}")
        assert response.status_code == 200, response.text
        return response.json()

    async def press_stop_on_library_prompt(self) -> None:
        [active] = [
            request
            for request in await self.get("/manual-queue")
            if request["status"] == ManualRequestStatus.PROCESSING.value
        ]
        await self.post(f"/manual-queue/{active['id']}/stop")

    async def accept_plan(self, *_args: Any, **_kwargs: Any) -> bool:
        """
        Подменяет ожидание сигнала в `plan_mode`: пользователь видит
        `plan_review` и выбирает вариант через API.
        """
        task = await self.get("")
        self.statuses_at_plan_decision.append(task["status"])
        logs = await self.get("/node-logs")
        [pending] = [log for log in logs if log["status"] == NodeLogStatus.AWAITING_DECISION.value]
        await self.post(
            "/decision",
            {"node_log_id": pending["id"], "option_id": PlanDecisionOption.ACCEPT_DEFAULT},
        )
        return True


@pytest.mark.usefixtures("redis_client")
class TestFullCycle:
    async def test_task_reaches_done(
        self,
        authed_client: AsyncClient,
        current_user: User,
        db_session: AsyncSession,
        worker_env: WorkerEnv,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        origin = init_bare_origin(tmp_path)
        repository = await _make_repository(db_session, origin)
        pipeline, nodes = await _make_pipeline(db_session, current_user.id)
        library_node = await _make_library_node(db_session, current_user.id)

        # 1. Создание задачи с репозиторием и LLM-аккаунтом (у пайплайна есть LLM-ноды).
        code = f"RR-{uuid.uuid4().hex[:5]}"
        account = await make_llm_account(db_session, owner_id=current_user.id)
        created = await authed_client.post(
            "/tasks",
            json={
                "code": code,
                "title": "E2E",
                "description": "Полный цикл",
                "llm_account_id": str(account.id),
                "repositories": [{"repository_id": str(repository.id), "role": "read_write"}],
            },
        )
        assert created.status_code == 201, created.text
        user = _User(authed_client, created.json()["id"])

        # 2. Пайплайн с отключённой нодой.
        await user.post(
            "/pipeline",
            {"pipeline_id": str(pipeline.id), "disabled_node_ids": [str(nodes["optional"].id)]},
        )
        library_prompt = await user.post("/library-prompts", {"node_id": str(library_node.id)})

        # 3. Автозапуск с датой в прошлом.
        past = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
        patched = await authed_client.patch(
            f"/tasks/{user.task_id}",
            json={"auto_start_enabled": True, "scheduled_start_at": past},
        )
        assert patched.status_code == 200, patched.text
        autostart = await run_scheduled_autostart_check(db_session, now=datetime.now(UTC))
        assert [str(task_id) for task_id in autostart.started_task_ids] == [user.task_id]

        # 4. Ход сессии: действия пользователя по ходу выполнения нод.
        monkeypatch.setattr("services.plan_mode.wait_for_task_signal", user.accept_plan)
        stop_presses: list[asyncio.Task[None]] = []

        async def press_stop_soon() -> None:
            await asyncio.sleep(_STOP_PRESS_DELAY_SECONDS)
            await user.press_stop_on_library_prompt()
            fake.message_delay_seconds = 0

        async def agent_and_user() -> None:
            query = fake.queries[-1]
            if query == _PREPARE_PROMPT.replace("{{task.code}}", code):
                await user.post(f"/library-prompts/{library_prompt['id']}/run")
                await user.post("/freeform", {"raw_prompt_text": _FREEFORM_PROMPT})
            elif query == _LIBRARY_PROMPT:
                fake.message_delay_seconds = _HANGING_TURN_DELAY_SECONDS
                stop_presses.append(asyncio.ensure_future(press_stop_soon()))
            elif query == _PLAN_PROMPT:
                can_use_tool = worker_env.options[0].can_use_tool
                assert can_use_tool is not None
                decision = await can_use_tool(
                    "ExitPlanMode",
                    {"plan": _PLAN_TEXT},
                    ToolPermissionContext(),
                )
                assert decision.behavior == "allow"

        fake = FakeClaudeAgentClient(
            messages_per_query=[[make_result_message()] for _ in range(5)],
            on_query=agent_and_user,
        )
        worker_env.client = fake
        await asyncio.wait_for(
            session_worker._run_task_session_async(  # noqa: SLF001
                uuid.UUID(user.task_id),
                start_after_order_index=None,
                continuation=False,
            ),
            timeout=60,
        )
        await asyncio.gather(*stop_presses)

        # 5. Итог.
        assert fake.queries == [
            f"Подготовь окружение задачи {code}",
            _LIBRARY_PROMPT,
            f"Код задачи: {code}",
            _PLAN_PROMPT,
            f"Реализуй: {_PLAN_TEXT}",
        ]
        assert fake.interrupted is True
        assert user.statuses_at_plan_decision == [TaskStatus.PLAN_REVIEW.value]
        task = await db_session.get(Task, uuid.UUID(user.task_id), populate_existing=True)
        assert task is not None
        assert task.status is TaskStatus.DONE

        logs = (
            (
                await db_session.execute(
                    sa.select(NodeLog)
                    .where(NodeLog.task_id == task.id)
                    .order_by(NodeLog.started_at),
                )
            )
            .scalars()
            .all()
        )
        assert [(log.trigger_type, log.status) for log in logs] == [
            (NodeLogTriggerType.PIPELINE, NodeLogStatus.SUCCESS),
            (NodeLogTriggerType.LIBRARY_MANUAL, NodeLogStatus.STOPPED),
            (NodeLogTriggerType.FREEFORM_MANUAL, NodeLogStatus.SUCCESS),
            (NodeLogTriggerType.PIPELINE, NodeLogStatus.SUCCESS),
            (NodeLogTriggerType.PIPELINE, NodeLogStatus.SUCCESS),
        ]
        assert all(log.node_id != nodes["optional"].id for log in logs)
        prompts = await user.get("/library-prompts")
        assert prompts[0]["last_run_status"] == LibraryPromptRunStatus.STOPPED.value
        remote_heads = run_command("git", "ls-remote", "--heads", str(origin), cwd=tmp_path)
        assert f"refs/heads/feature/{code}" in remote_heads
