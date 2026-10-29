"""
Роутер `api/tasks/` — жизненный цикл задачи (раздел 2.3, 2.4, 7, 8, 9.6 ТЗ).
"""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.enums import (
    LibraryPromptRunStatus,
    ManualRequestStatus,
    NodeLogStatus,
    NodeLogTriggerType,
    NodeType,
    RemoteControlStatus,
    RepositoryRole,
    TaskStatus,
)
from db.models.env_vars import TaskEnvVariable
from db.models.logs import NodeLog
from db.models.pipelines import Node, Pipeline
from db.models.prompts import TaskLibraryPrompt, TaskManualRequestQueue
from db.models.repositories import Repository
from db.models.tasks import Task
from db.models.users import User
from services.plan_mode import PlanDecisionOption, encode_decision
from services.task_control import (
    TaskControlCommand,
    consume_bridge_reconnect,
    is_manual_stop_requested,
    read_task_control,
)
from services.task_signal import wait_for_task_signal
from tests.factories import make_llm_account, make_node_log, make_pipeline, make_repository

if TYPE_CHECKING:
    from httpx import AsyncClient
    from redis.asyncio import Redis

pytestmark = pytest.mark.usefixtures("redis_container")


def _owner(task_body: dict[str, Any]) -> uuid.UUID:
    """Автор задачи — и автор пайплайнов/промтов, которые к ней привязывает тест."""
    return uuid.UUID(task_body["created_by"])


async def _create_task(
    client: AsyncClient,
    *,
    code: str | None = None,
) -> dict[str, Any]:
    response = await client.post(
        "/tasks",
        json={
            "code": code or f"RR-{uuid.uuid4().hex[:8]}",
            "title": "Тестовая задача",
            "description": "Описание",
        },
    )
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


async def _create_launchable_task(client: AsyncClient, db_session: AsyncSession) -> dict[str, Any]:
    """Задача с привязанным пайплайном — без него запуск отклоняется (раздел 13.1)."""
    body = await _create_task(client)
    task = await db_session.get(Task, uuid.UUID(body["id"]))
    assert task is not None
    task.pipeline_id = (await make_pipeline(db_session, created_by=task.created_by)).id
    await db_session.flush()
    return body


async def test_create_task_sets_creator_and_default_status(
    authed_client: AsyncClient,
    current_user: User,
) -> None:
    body = await _create_task(authed_client)

    assert body["status"] == TaskStatus.NEW.value
    assert body["pipeline_id"] is None


async def test_list_tasks_filters_by_status(authed_client: AsyncClient) -> None:
    await _create_task(authed_client)

    response = await authed_client.get("/tasks", params={"status_filter": TaskStatus.DONE.value})

    assert response.status_code == 200
    assert response.json() == []


async def test_get_task_returns_404_for_unknown_id(authed_client: AsyncClient) -> None:
    response = await authed_client.get(f"/tasks/{uuid.uuid4()}")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


async def test_awaiting_count_reflects_awaiting_input_and_plan_review_tasks(
    authed_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    before = (await authed_client.get("/tasks/awaiting-count")).json()["count"]
    task_body = await _create_task(authed_client)
    task = await db_session.get(Task, uuid.UUID(task_body["id"]))
    assert task is not None
    task.status = TaskStatus.AWAITING_INPUT
    await db_session.flush()

    response = await authed_client.get("/tasks/awaiting-count")

    assert response.status_code == 200
    assert response.json()["count"] == before + 1


async def test_bind_pipeline_atomically_creates_task_nodes(
    authed_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    task_body = await _create_task(authed_client)
    pipeline = Pipeline(name="Демо-пайплайн", created_by=_owner(task_body))
    db_session.add(pipeline)
    await db_session.flush()
    node_a = Node(
        created_by=_owner(task_body),
        pipeline_id=pipeline.id,
        order_index=0,
        name="Шаг 1",
        node_type=NodeType.PLAIN_PROMPT,
        prompt_template="Привет",
        is_library_item=False,
    )
    node_b = Node(
        created_by=_owner(task_body),
        pipeline_id=pipeline.id,
        order_index=1,
        name="Шаг 2",
        node_type=NodeType.PLAIN_PROMPT,
        prompt_template="Пока",
        is_library_item=False,
    )
    db_session.add_all([node_a, node_b])
    await db_session.flush()

    response = await authed_client.post(
        f"/tasks/{task_body['id']}/pipeline",
        json={"pipeline_id": str(pipeline.id)},
    )

    assert response.status_code == 200
    assert response.json()["pipeline_id"] == str(pipeline.id)


async def test_bind_pipeline_rejects_empty_pipeline(
    authed_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    task_body = await _create_task(authed_client)
    empty_pipeline = Pipeline(name="Пустой пайплайн", created_by=_owner(task_body))
    db_session.add(empty_pipeline)
    await db_session.flush()

    response = await authed_client.post(
        f"/tasks/{task_body['id']}/pipeline",
        json={"pipeline_id": str(empty_pipeline.id)},
    )

    assert response.status_code == 422


class TestBindArchivedPipeline:
    """Раздел 3.2: архивный пайплайн к задаче не привязывается."""

    async def test_rejected(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        task_body = await _create_task(authed_client)
        archived = Pipeline(name="Архивный", is_archived=True, created_by=_owner(task_body))
        db_session.add(archived)
        await db_session.flush()
        db_session.add(
            Node(
                created_by=_owner(task_body),
                pipeline_id=archived.id,
                order_index=0,
                name="шаг",
                node_type=NodeType.PLAIN_PROMPT,
                prompt_template="x",
                is_library_item=False,
            ),
        )
        await db_session.flush()

        response = await authed_client.post(
            f"/tasks/{task_body['id']}/pipeline",
            json={"pipeline_id": str(archived.id)},
        )

        assert response.status_code == 409


async def test_bind_pipeline_rejects_task_not_in_new_status(
    authed_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    task_body = await _create_task(authed_client)
    task = await db_session.get(Task, uuid.UUID(task_body["id"]))
    assert task is not None
    task.status = TaskStatus.DONE
    await db_session.flush()
    pipeline = Pipeline(name="Пайплайн", created_by=_owner(task_body))
    db_session.add(pipeline)
    await db_session.flush()
    db_session.add(
        Node(
            created_by=_owner(task_body),
            pipeline_id=pipeline.id,
            order_index=0,
            name="Шаг",
            node_type=NodeType.PLAIN_PROMPT,
            prompt_template="x",
            is_library_item=False,
        ),
    )
    await db_session.flush()

    response = await authed_client.post(
        f"/tasks/{task_body['id']}/pipeline",
        json={"pipeline_id": str(pipeline.id)},
    )

    assert response.status_code == 422


async def test_start_task_transitions_to_queued_and_enqueues_session_worker(
    authed_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task_body = await _create_launchable_task(authed_client, db_session)
    enqueued_task_ids: list[str] = []
    monkeypatch.setattr(
        "api.tasks.lifecycle.run_task_session",
        SimpleNamespace(delay=enqueued_task_ids.append),
    )

    response = await authed_client.post(f"/tasks/{task_body['id']}/start")

    assert response.status_code == 200
    assert response.json()["status"] == TaskStatus.QUEUED.value
    assert enqueued_task_ids == [task_body["id"]]


async def test_start_task_rejects_task_not_in_new_status(
    authed_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task_body = await _create_launchable_task(authed_client, db_session)
    task = await db_session.get(Task, uuid.UUID(task_body["id"]))
    assert task is not None
    task.status = TaskStatus.DONE
    await db_session.flush()
    monkeypatch.setattr(
        "api.tasks.lifecycle.run_task_session",
        SimpleNamespace(delay=lambda _task_id: None),
    )

    response = await authed_client.post(f"/tasks/{task_body['id']}/start")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"


async def test_list_node_logs_returns_history_in_order(
    authed_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    task_body = await _create_task(authed_client)
    task_id = uuid.UUID(task_body["id"])
    db_session.add(
        NodeLog(
            task_id=task_id,
            trigger_type=NodeLogTriggerType.FREEFORM_MANUAL,
            status=NodeLogStatus.FAILED,
            error_message="Превышен таймаут выполнения",
        ),
    )
    await db_session.flush()

    response = await authed_client.get(f"/tasks/{task_body['id']}/node-logs")

    assert response.status_code == 200
    entries = response.json()
    assert len(entries) == 1
    assert entries[0]["status"] == NodeLogStatus.FAILED.value
    assert entries[0]["error_message"] == "Превышен таймаут выполнения"


async def test_submit_decision_encodes_and_publishes_signal(
    authed_client: AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
) -> None:
    task_body = await _create_task(authed_client)
    task_id = uuid.UUID(task_body["id"])
    node_log = NodeLog(
        task_id=task_id,
        trigger_type=NodeLogTriggerType.PIPELINE,
        status=NodeLogStatus.AWAITING_DECISION,
    )
    db_session.add(node_log)
    await db_session.flush()
    wait_task = asyncio.create_task(wait_for_task_signal(redis_client, task_id, timeout=5))
    await asyncio.sleep(0.1)  # даём подписке успеть зарегистрироваться до publish

    response = await authed_client.post(
        f"/tasks/{task_body['id']}/decision",
        json={
            "node_log_id": str(node_log.id),
            "option_id": PlanDecisionOption.REVISE,
            "feedback_text": "Уточни шаг 2",
        },
    )

    assert response.status_code == 204
    assert await wait_task is True
    await db_session.refresh(node_log)
    assert node_log.user_input_text == encode_decision(
        PlanDecisionOption.REVISE,
        feedback_text="Уточни шаг 2",
    )


async def test_submit_decision_rejects_node_log_not_awaiting_decision(
    authed_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    task_body = await _create_task(authed_client)
    node_log = NodeLog(
        task_id=uuid.UUID(task_body["id"]),
        trigger_type=NodeLogTriggerType.PIPELINE,
        status=NodeLogStatus.SUCCESS,
    )
    db_session.add(node_log)
    await db_session.flush()

    response = await authed_client.post(
        f"/tasks/{task_body['id']}/decision",
        json={"node_log_id": str(node_log.id), "option_id": PlanDecisionOption.ACCEPT_AUTO},
    )

    assert response.status_code == 422


async def test_submit_decision_rejects_node_log_from_another_task(
    authed_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    task_body = await _create_task(authed_client)
    other_task_body = await _create_task(authed_client)
    node_log = NodeLog(
        task_id=uuid.UUID(other_task_body["id"]),
        trigger_type=NodeLogTriggerType.PIPELINE,
        status=NodeLogStatus.AWAITING_DECISION,
    )
    db_session.add(node_log)
    await db_session.flush()

    response = await authed_client.post(
        f"/tasks/{task_body['id']}/decision",
        json={"node_log_id": str(node_log.id), "option_id": PlanDecisionOption.ACCEPT_AUTO},
    )

    assert response.status_code == 404


async def _create_task_in_status(
    client: AsyncClient,
    db_session: AsyncSession,
    status: TaskStatus,
) -> dict[str, Any]:
    body = await _create_task(client)
    task = await db_session.get(Task, uuid.UUID(body["id"]))
    assert task is not None
    task.status = status
    # Ручные промты и мост выполняет LLM — у такой задачи есть аккаунт (раздел 3.1).
    task.llm_account_id = (await make_llm_account(db_session, owner_id=task.created_by)).id
    await db_session.flush()
    return body


async def test_submit_freeform_prompt_enqueues_manual_request(
    authed_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    task_body = await _create_task_in_status(authed_client, db_session, TaskStatus.IN_PROGRESS)

    response = await authed_client.post(
        f"/tasks/{task_body['id']}/freeform",
        json={"raw_prompt_text": "Проверь тесты"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == ManualRequestStatus.QUEUED.value
    request = await db_session.get(TaskManualRequestQueue, uuid.UUID(body["id"]))
    assert request is not None
    assert request.raw_prompt_text == "Проверь тесты"


async def test_add_and_run_library_prompt(
    authed_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    task_body = await _create_task_in_status(authed_client, db_session, TaskStatus.IN_PROGRESS)
    node = Node(
        created_by=_owner(task_body),
        name="Библиотечный промт",
        node_type=NodeType.PLAIN_PROMPT,
        prompt_template="Сделай X",
        is_library_item=True,
    )
    db_session.add(node)
    await db_session.flush()

    add_response = await authed_client.post(
        f"/tasks/{task_body['id']}/library-prompts",
        json={"node_id": str(node.id)},
    )
    assert add_response.status_code == 201
    task_library_prompt_id = add_response.json()["id"]

    run_response = await authed_client.post(
        f"/tasks/{task_body['id']}/library-prompts/{task_library_prompt_id}/run",
    )

    assert run_response.status_code == 201
    assert run_response.json()["status"] == ManualRequestStatus.QUEUED.value
    task_library_prompt = await db_session.get(
        TaskLibraryPrompt,
        uuid.UUID(task_library_prompt_id),
    )
    assert task_library_prompt is not None
    assert task_library_prompt.last_run_status == LibraryPromptRunStatus.QUEUED


async def test_cancel_manual_queue_request(
    authed_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    task_body = await _create_task_in_status(authed_client, db_session, TaskStatus.IN_PROGRESS)
    response = await authed_client.post(
        f"/tasks/{task_body['id']}/freeform",
        json={"raw_prompt_text": "Отменяемый запрос"},
    )
    request_id = response.json()["id"]

    cancel_response = await authed_client.delete(
        f"/tasks/{task_body['id']}/manual-queue/{request_id}",
    )

    assert cancel_response.status_code == 204
    request = await db_session.get(TaskManualRequestQueue, uuid.UUID(request_id))
    assert request is not None
    assert request.status == ManualRequestStatus.CANCELLED


async def test_cancel_manual_queue_request_rejects_already_processed(
    authed_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    task_body = await _create_task_in_status(authed_client, db_session, TaskStatus.IN_PROGRESS)
    response = await authed_client.post(
        f"/tasks/{task_body['id']}/freeform",
        json={"raw_prompt_text": "Уже обработанный запрос"},
    )
    request_id = uuid.UUID(response.json()["id"])
    request = await db_session.get(TaskManualRequestQueue, request_id)
    assert request is not None
    request.status = ManualRequestStatus.DONE
    await db_session.flush()

    cancel_response = await authed_client.delete(
        f"/tasks/{task_body['id']}/manual-queue/{request_id}",
    )

    assert cancel_response.status_code == 409


async def _make_repository(db_session: AsyncSession, name: str = "backend") -> Repository:
    return await make_repository(db_session, name=name)


async def test_create_task_attaches_repositories_and_llm_account(
    authed_client: AsyncClient,
    db_session: AsyncSession,
    current_user: User,
) -> None:
    repository = await _make_repository(db_session)
    llm_account = await make_llm_account(db_session, owner_id=current_user.id)

    response = await authed_client.post(
        "/tasks",
        json={
            "code": "RR-10001",
            "title": "t",
            "description": "d",
            "llm_account_id": str(llm_account.id),
            "repositories": [{"repository_id": str(repository.id), "role": "read_write"}],
        },
    )

    assert response.status_code == 201, response.text
    assert response.json()["llm_account_id"] == str(llm_account.id)
    repositories = await authed_client.get(f"/tasks/{response.json()['id']}/repositories")
    assert repositories.status_code == 200
    [attached] = repositories.json()
    assert attached["repository_id"] == str(repository.id)
    assert attached["role"] == RepositoryRole.READ_WRITE.value
    assert attached["branch_name"] == "feature/RR-10001"
    assert attached["base_branch"] == "main"


async def test_create_task_rejects_unknown_repository(authed_client: AsyncClient) -> None:
    response = await authed_client.post(
        "/tasks",
        json={
            "code": "RR-10002",
            "title": "t",
            "description": "d",
            "repositories": [{"repository_id": str(uuid.uuid4()), "role": "read_only"}],
        },
    )

    assert response.status_code == 404


async def test_create_task_rejects_duplicate_repository(
    authed_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    repository = await _make_repository(db_session)
    attached = {"repository_id": str(repository.id), "role": "read_only"}

    response = await authed_client.post(
        "/tasks",
        json={"code": "RR-10003", "title": "t", "description": "d", "repositories": [attached] * 2},
    )

    assert response.status_code == 422


async def test_update_task_sets_autostart_while_new(authed_client: AsyncClient) -> None:
    task_body = await _create_task(authed_client)

    response = await authed_client.patch(
        f"/tasks/{task_body['id']}",
        json={"auto_start_enabled": True, "scheduled_start_at": "2030-01-01T09:00:00Z"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["auto_start_enabled"] is True
    assert response.json()["scheduled_start_at"].startswith("2030-01-01T09:00:00")


@pytest.mark.parametrize(
    ("status", "payload", "expected_code"),
    [
        (TaskStatus.IN_PROGRESS, {"title": "новое"}, 422),
        (TaskStatus.IN_PROGRESS, {"auto_accept_plan": True}, 200),
        (TaskStatus.DONE, {"auto_accept_plan": True}, 422),
    ],
)
async def test_update_task_enforces_status_rules(
    authed_client: AsyncClient,
    db_session: AsyncSession,
    status: TaskStatus,
    payload: dict[str, Any],
    expected_code: int,
) -> None:
    task_body = await _create_task(authed_client)
    task = await db_session.get(Task, uuid.UUID(task_body["id"]))
    assert task is not None
    task.status = status
    await db_session.flush()

    response = await authed_client.patch(f"/tasks/{task_body['id']}", json=payload)

    assert response.status_code == expected_code, response.text


async def test_restart_task_reruns_failed_node(
    authed_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task_body = await _create_launchable_task(authed_client, db_session)
    task = await db_session.get(Task, uuid.UUID(task_body["id"]))
    assert task is not None
    task.status = TaskStatus.FAILED
    task.last_failed_order_index = 3
    await db_session.flush()
    calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
    monkeypatch.setattr(
        "api.tasks.lifecycle.run_task_session",
        SimpleNamespace(delay=lambda *args, **kwargs: calls.append((args, kwargs))),
    )

    response = await authed_client.post(f"/tasks/{task_body['id']}/restart")

    assert response.status_code == 200, response.text
    # Ноды с order_index <= 2 пропускаются — упавшая нода 3 выполняется заново.
    assert calls == [((task_body["id"],), {"start_after_order_index": 2})]


async def test_restart_task_rejects_task_not_failed(
    authed_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task_body = await _create_task(authed_client)
    monkeypatch.setattr("api.tasks.lifecycle.run_task_session", SimpleNamespace(delay=None))

    response = await authed_client.post(f"/tasks/{task_body['id']}/restart")

    assert response.status_code == 422


# --- Управление задачей: пауза, продолжение, остановка, отмена (раздел 14.2) ---


@pytest.mark.parametrize(
    ("action", "status", "command"),
    [
        ("pause", TaskStatus.IN_PROGRESS, TaskControlCommand.PAUSE),
        ("resume", TaskStatus.PAUSED, TaskControlCommand.RESUME),
        ("stop", TaskStatus.IN_PROGRESS, TaskControlCommand.STOP),
        ("stop", TaskStatus.PAUSED, TaskControlCommand.STOP),
    ],
)
async def test_task_control_actions_hand_command_to_worker(
    authed_client: AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    action: str,
    status: TaskStatus,
    command: TaskControlCommand,
) -> None:
    task_body = await _create_task_in_status(authed_client, db_session, status)
    task_id = uuid.UUID(task_body["id"])
    waiter = asyncio.ensure_future(wait_for_task_signal(redis_client, task_id, timeout=5))
    await asyncio.sleep(0.1)

    response = await authed_client.post(f"/tasks/{task_id}/{action}")

    assert response.status_code == 202, response.text
    assert await waiter is True
    assert await read_task_control(redis_client, task_id) is command
    task = await db_session.get(Task, task_id)
    assert task is not None
    # Статус меняет только воркер, владеющий сессией.
    assert task.status is status


@pytest.mark.parametrize(
    ("action", "status"),
    [
        ("pause", TaskStatus.NEW),
        ("pause", TaskStatus.PAUSED),
        ("resume", TaskStatus.IN_PROGRESS),
        ("stop", TaskStatus.QUEUED),
        ("stop", TaskStatus.DONE),
    ],
)
async def test_task_control_actions_reject_wrong_status(
    authed_client: AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    action: str,
    status: TaskStatus,
) -> None:
    task_body = await _create_task_in_status(authed_client, db_session, status)

    response = await authed_client.post(f"/tasks/{task_body['id']}/{action}")

    assert response.status_code == 409
    assert await read_task_control(redis_client, uuid.UUID(task_body["id"])) is None


async def test_cancel_queued_task_returns_it_to_new_and_disables_autostart(
    authed_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    task_body = await _create_task_in_status(authed_client, db_session, TaskStatus.QUEUED)
    task = await db_session.get(Task, uuid.UUID(task_body["id"]))
    assert task is not None
    task.auto_start_enabled = True
    await db_session.flush()

    response = await authed_client.post(f"/tasks/{task_body['id']}/cancel")

    assert response.status_code == 200, response.text
    assert response.json()["status"] == TaskStatus.NEW.value
    assert response.json()["auto_start_enabled"] is False


async def test_cancel_rejects_task_already_running(
    authed_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    task_body = await _create_task_in_status(authed_client, db_session, TaskStatus.IN_PROGRESS)

    response = await authed_client.post(f"/tasks/{task_body['id']}/cancel")

    assert response.status_code == 409


# --- Ноды задачи (раздел 13.1, 13.2) ---


async def _bind_pipeline_with_nodes(
    client: AsyncClient,
    db_session: AsyncSession,
    task_body: dict[str, Any],
    count: int,
) -> list[dict[str, Any]]:
    pipeline = Pipeline(
        name=f"p-{uuid.uuid4().hex[:6]}",
        is_archived=False,
        created_by=_owner(task_body),
    )
    db_session.add(pipeline)
    await db_session.flush()
    for order_index in range(count):
        db_session.add(
            Node(
                created_by=_owner(task_body),
                pipeline_id=pipeline.id,
                order_index=order_index,
                name=f"node-{order_index}",
                node_type=NodeType.PLAIN_PROMPT,
                prompt_template="x",
                is_skipped=False,
                is_library_item=False,
                is_archived=False,
            ),
        )
    await db_session.flush()
    response = await client.post(
        f"/tasks/{task_body['id']}/pipeline",
        json={"pipeline_id": str(pipeline.id)},
    )
    assert response.status_code == 200, response.text
    nodes_response = await client.get(f"/tasks/{task_body['id']}/nodes")
    assert nodes_response.status_code == 200
    nodes: list[dict[str, Any]] = nodes_response.json()
    return nodes


async def test_task_nodes_can_be_toggled_while_new(
    authed_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    task_body = await _create_task(authed_client)
    nodes = await _bind_pipeline_with_nodes(authed_client, db_session, task_body, 2)
    assert [(node["name"], node["is_enabled"], node["editable"]) for node in nodes] == [
        ("node-0", True, True),
        ("node-1", True, True),
    ]

    response = await authed_client.patch(
        f"/tasks/{task_body['id']}/nodes/{nodes[1]['id']}",
        json={"is_enabled": False},
    )

    assert response.status_code == 200, response.text
    assert response.json()["is_enabled"] is False


async def test_failed_task_locks_nodes_up_to_failure_point(
    authed_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    task_body = await _create_task(authed_client)
    nodes = await _bind_pipeline_with_nodes(authed_client, db_session, task_body, 3)
    task = await db_session.get(Task, uuid.UUID(task_body["id"]))
    assert task is not None
    task.status = TaskStatus.FAILED
    task.last_failed_order_index = 1
    await make_node_log(db_session, task_id=task.id, node_id=uuid.UUID(nodes[1]["node_id"]))

    locked = await authed_client.patch(
        f"/tasks/{task_body['id']}/nodes/{nodes[1]['id']}",
        json={"is_enabled": False},
    )
    allowed = await authed_client.patch(
        f"/tasks/{task_body['id']}/nodes/{nodes[2]['id']}",
        json={"is_enabled": False},
    )
    listed = (await authed_client.get(f"/tasks/{task_body['id']}/nodes")).json()

    assert locked.status_code == 409
    assert allowed.status_code == 200
    assert [node["editable"] for node in listed] == [False, False, True]


class TestPauseAfterNode:
    """Раздел 13.1, 13.2: отметка «пауза после» меняется и у запущенной задачи."""

    async def test_set_while_running(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        task_body = await _create_task(authed_client)
        nodes = await _bind_pipeline_with_nodes(authed_client, db_session, task_body, 2)
        task = await db_session.get(Task, uuid.UUID(task_body["id"]))
        assert task is not None
        task.status = TaskStatus.IN_PROGRESS
        await db_session.flush()

        response = await authed_client.patch(
            f"/tasks/{task_body['id']}/nodes/{nodes[0]['id']}",
            json={"pause_after": True},
        )
        listed = (await authed_client.get(f"/tasks/{task_body['id']}/nodes")).json()

        assert response.status_code == 200, response.text
        assert response.json()["pause_after"] is True
        assert [(node["pause_after"], node["is_enabled"]) for node in listed] == [
            (True, True),
            (False, True),
        ]

    async def test_empty_body_rejected(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        task_body = await _create_task(authed_client)
        nodes = await _bind_pipeline_with_nodes(authed_client, db_session, task_body, 1)

        response = await authed_client.patch(
            f"/tasks/{task_body['id']}/nodes/{nodes[0]['id']}",
            json={},
        )

        assert response.status_code == 422


class TestCustomTaskNodes:
    """Раздел 13.1: свои промты задачи — вставка, правка, удаление и изоляция от `/nodes`."""

    _PROMPT = {"name": "Уточнения", "node_type": "plain_prompt", "prompt_template": "Спроси"}

    async def _insert(
        self,
        client: AsyncClient,
        task_body: dict[str, Any],
        after: dict[str, Any] | None,
    ) -> dict[str, Any]:
        response = await client.post(
            f"/tasks/{task_body['id']}/nodes",
            json={**self._PROMPT, "after_task_node_id": after["id"] if after else None},
        )
        assert response.status_code == 201, response.text
        created: dict[str, Any] = response.json()
        return created

    async def test_insert_edit_delete(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        task_body = await _create_task(authed_client)
        nodes = await _bind_pipeline_with_nodes(authed_client, db_session, task_body, 2)
        path = f"/tasks/{task_body['id']}/nodes"

        created = await self._insert(authed_client, task_body, nodes[0])
        edited = await authed_client.patch(
            f"{path}/{created['id']}",
            json={"content": {**self._PROMPT, "prompt_template": "Спроси про CSV"}},
        )
        listed = (await authed_client.get(path)).json()
        deleted = await authed_client.delete(f"{path}/{created['id']}")

        assert (created["is_custom"], created["order_index"]) == (True, 1)
        assert edited.json()["prompt_template"] == "Спроси про CSV"
        assert [node["name"] for node in listed] == ["node-0", "Уточнения", "node-1"]
        assert [node["prompt_template"] for node in listed] == [None, "Спроси про CSV", None]
        assert deleted.status_code == 204
        assert [node["name"] for node in (await authed_client.get(path)).json()] == [
            "node-0",
            "node-1",
        ]

    @pytest.mark.parametrize(
        ("body", "status"),
        [
            ({"node_type": "script"}, 422),
            ({"node_type": "slash_command", "command_invocation": "/review"}, 201),
        ],
    )
    async def test_node_types(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
        body: dict[str, Any],
        status: int,
    ) -> None:
        task_body = await _create_task(authed_client)
        await _bind_pipeline_with_nodes(authed_client, db_session, task_body, 1)

        response = await authed_client.post(
            f"/tasks/{task_body['id']}/nodes",
            json={**self._PROMPT, **body},
        )

        assert response.status_code == status, response.text

    async def test_pause_after_set_on_insert(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        task_body = await _create_task(authed_client)
        await _bind_pipeline_with_nodes(authed_client, db_session, task_body, 1)

        response = await authed_client.post(
            f"/tasks/{task_body['id']}/nodes",
            json={**self._PROMPT, "pause_after": True},
        )

        assert response.status_code == 201, response.text
        assert (response.json()["pause_after"], response.json()["is_enabled"]) == (True, True)

    async def test_pipeline_node_not_attached_as_library_prompt(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        task_body = await _create_task(authed_client)
        nodes = await _bind_pipeline_with_nodes(authed_client, db_session, task_body, 1)

        response = await authed_client.post(
            f"/tasks/{task_body['id']}/library-prompts",
            json={"node_id": nodes[0]["node_id"]},
        )

        assert response.status_code == 409

    async def test_pipeline_node_not_deleted(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        task_body = await _create_task(authed_client)
        nodes = await _bind_pipeline_with_nodes(authed_client, db_session, task_body, 1)

        response = await authed_client.delete(f"/tasks/{task_body['id']}/nodes/{nodes[0]['id']}")

        assert response.status_code == 409

    async def test_hidden_from_library_and_builder(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        task_body = await _create_task(authed_client)
        await _bind_pipeline_with_nodes(authed_client, db_session, task_body, 1)
        created = await self._insert(authed_client, task_body, None)
        node_id = created["node_id"]

        listed = (await authed_client.get("/nodes")).json()
        fetched = await authed_client.patch(f"/nodes/{node_id}", json={"name": "чужое"})
        attached = await authed_client.post(
            f"/tasks/{task_body['id']}/library-prompts",
            json={"node_id": node_id},
        )

        assert node_id not in {node["id"] for node in listed}
        assert fetched.status_code == 404
        assert attached.status_code == 409


# --- Ручные запросы: активная сессия, список, кнопка ■ (раздел 7.3, 8.2) ---


@pytest.mark.parametrize(
    "status",
    [TaskStatus.NEW, TaskStatus.QUEUED, TaskStatus.FAILED, TaskStatus.DONE],
)
async def test_manual_prompts_require_active_session(
    authed_client: AsyncClient,
    db_session: AsyncSession,
    status: TaskStatus,
) -> None:
    task_body = await _create_task_in_status(authed_client, db_session, status)

    response = await authed_client.post(
        f"/tasks/{task_body['id']}/freeform",
        json={"raw_prompt_text": "Проверь тесты"},
    )

    assert response.status_code == 409


async def _add_library_prompt(
    client: AsyncClient,
    db_session: AsyncSession,
    task_body: dict[str, Any],
) -> str:
    node = Node(
        created_by=_owner(task_body),
        name="Ревью кода",
        node_type=NodeType.PLAIN_PROMPT,
        prompt_template="Сделай ревью",
        is_library_item=True,
    )
    db_session.add(node)
    await db_session.flush()
    response = await client.post(
        f"/tasks/{task_body['id']}/library-prompts",
        json={"node_id": str(node.id)},
    )
    assert response.status_code == 201
    task_library_prompt_id: str = response.json()["id"]
    return task_library_prompt_id


async def test_library_prompts_list_exposes_active_request_for_stop_button(
    authed_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    task_body = await _create_task_in_status(authed_client, db_session, TaskStatus.IN_PROGRESS)
    task_library_prompt_id = await _add_library_prompt(authed_client, db_session, task_body)

    before = (await authed_client.get(f"/tasks/{task_body['id']}/library-prompts")).json()
    run = await authed_client.post(
        f"/tasks/{task_body['id']}/library-prompts/{task_library_prompt_id}/run",
    )
    after = (await authed_client.get(f"/tasks/{task_body['id']}/library-prompts")).json()
    queue = (await authed_client.get(f"/tasks/{task_body['id']}/manual-queue")).json()

    assert before == [
        {
            "id": task_library_prompt_id,
            "node_id": before[0]["node_id"],
            "last_run_status": LibraryPromptRunStatus.NEVER_RUN.value,
            "last_run_at": None,
            "name": "Ревью кода",
            "node_type": NodeType.PLAIN_PROMPT.value,
            "active_request_id": None,
        },
    ]
    assert after[0]["last_run_status"] == LibraryPromptRunStatus.QUEUED.value
    assert after[0]["active_request_id"] == run.json()["id"]
    assert [request["id"] for request in queue] == [run.json()["id"]]


async def test_stop_button_cancels_queued_request(
    authed_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    task_body = await _create_task_in_status(authed_client, db_session, TaskStatus.IN_PROGRESS)
    request_id = (
        await authed_client.post(
            f"/tasks/{task_body['id']}/freeform",
            json={"raw_prompt_text": "Отменить"},
        )
    ).json()["id"]

    response = await authed_client.post(
        f"/tasks/{task_body['id']}/manual-queue/{request_id}/stop",
    )

    assert response.status_code == 202
    request = await db_session.get(TaskManualRequestQueue, uuid.UUID(request_id))
    assert request is not None
    assert request.status is ManualRequestStatus.CANCELLED
    queue = (await authed_client.get(f"/tasks/{task_body['id']}/manual-queue")).json()
    assert queue == []


async def test_stop_button_interrupts_processing_request(
    authed_client: AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
) -> None:
    task_body = await _create_task_in_status(authed_client, db_session, TaskStatus.IN_PROGRESS)
    task_id = uuid.UUID(task_body["id"])
    request_id = uuid.UUID(
        (
            await authed_client.post(
                f"/tasks/{task_id}/freeform",
                json={"raw_prompt_text": "Долгий запрос"},
            )
        ).json()["id"],
    )
    request = await db_session.get(TaskManualRequestQueue, request_id)
    assert request is not None
    request.status = ManualRequestStatus.PROCESSING
    await db_session.flush()

    response = await authed_client.post(f"/tasks/{task_id}/manual-queue/{request_id}/stop")
    finished_request = request
    finished_request.status = ManualRequestStatus.DONE
    await db_session.flush()
    late = await authed_client.post(f"/tasks/{task_id}/manual-queue/{request_id}/stop")

    assert response.status_code == 202
    assert await is_manual_stop_requested(redis_client, task_id, request_id)
    assert late.status_code == 409


async def _make_script_pipeline(
    db_session: AsyncSession,
    owner_id: uuid.UUID,
) -> tuple[Pipeline, list[Node]]:
    """Скрипт, его потребитель и нода, пропускаемая по умолчанию."""
    pipeline = Pipeline(name=f"p-{uuid.uuid4().hex[:6]}", is_archived=False, created_by=owner_id)
    db_session.add(pipeline)
    await db_session.flush()
    specs = [
        ("script", NodeType.SCRIPT, None, False),
        ("consumer", NodeType.PLAIN_PROMPT, "Разбери {{node.script_output}}", False),
        ("optional", NodeType.PLAIN_PROMPT, "необязательно", True),
    ]
    nodes = [
        Node(
            created_by=owner_id,
            pipeline_id=pipeline.id,
            order_index=order_index,
            name=name,
            node_type=node_type,
            prompt_template=prompt_template,
            script_content="echo hi" if node_type is NodeType.SCRIPT else None,
            is_skipped=is_skipped,
            is_library_item=False,
            is_archived=False,
        )
        for order_index, (name, node_type, prompt_template, is_skipped) in enumerate(specs)
    ]
    db_session.add_all(nodes)
    await db_session.flush()
    return pipeline, nodes


class TestBindPipelineNodeSelection:
    @pytest.mark.parametrize(
        ("disabled", "expected"),
        [
            (None, [True, True, False]),
            ([0], [False, True, True]),
        ],
        ids=["is_skipped_default", "explicit_choice"],
    )
    async def test_enabled_flags(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
        disabled: list[int] | None,
        expected: list[bool],
    ) -> None:
        task_body = await _create_task(authed_client)
        pipeline, nodes = await _make_script_pipeline(db_session, _owner(task_body))
        body: dict[str, Any] = {"pipeline_id": str(pipeline.id)}
        if disabled is not None:
            body["disabled_node_ids"] = [str(nodes[index].id) for index in disabled]

        response = await authed_client.post(f"/tasks/{task_body['id']}/pipeline", json=body)

        assert response.status_code == 200, response.text
        task_nodes = (await authed_client.get(f"/tasks/{task_body['id']}/nodes")).json()
        assert [node["is_enabled"] for node in task_nodes] == expected

    async def test_rejects_foreign_node(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        task_body = await _create_task(authed_client)
        pipeline, _nodes = await _make_script_pipeline(db_session, _owner(task_body))

        response = await authed_client.post(
            f"/tasks/{task_body['id']}/pipeline",
            json={"pipeline_id": str(pipeline.id), "disabled_node_ids": [str(uuid.uuid4())]},
        )

        assert response.status_code == 422
        task = (await authed_client.get(f"/tasks/{task_body['id']}")).json()
        assert task["pipeline_id"] is None


class TestNodeDependents:
    async def test_task_node(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        task_body = await _create_task(authed_client)
        pipeline, _nodes = await _make_script_pipeline(db_session, _owner(task_body))
        await authed_client.post(
            f"/tasks/{task_body['id']}/pipeline",
            json={"pipeline_id": str(pipeline.id)},
        )
        task_nodes = (await authed_client.get(f"/tasks/{task_body['id']}/nodes")).json()

        response = await authed_client.get(
            f"/tasks/{task_body['id']}/nodes/{task_nodes[0]['id']}/dependents",
        )

        assert response.status_code == 200
        assert [node["name"] for node in response.json()] == ["consumer"]

    @pytest.mark.parametrize(
        ("enabled", "expected"),
        [([0, 1], ["consumer"]), ([0], [])],
        ids=["consumer_enabled", "consumer_disabled"],
    )
    async def test_pipeline_node(
        self,
        authed_client: AsyncClient,
        current_user: User,
        db_session: AsyncSession,
        enabled: list[int],
        expected: list[str],
    ) -> None:
        pipeline, nodes = await _make_script_pipeline(db_session, current_user.id)

        response = await authed_client.post(
            f"/pipelines/{pipeline.id}/dependents",
            json={
                "node_id": str(nodes[0].id),
                "enabled_node_ids": [str(nodes[index].id) for index in enabled],
            },
        )

        assert response.status_code == 200
        assert [node["name"] for node in response.json()] == expected

    async def test_unknown_node_is_404(
        self,
        authed_client: AsyncClient,
        current_user: User,
        db_session: AsyncSession,
    ) -> None:
        pipeline, _nodes = await _make_script_pipeline(db_session, current_user.id)

        response = await authed_client.post(
            f"/pipelines/{pipeline.id}/dependents",
            json={"node_id": str(uuid.uuid4()), "enabled_node_ids": []},
        )

        assert response.status_code == 404


async def _task_in_status(
    authed_client: AsyncClient,
    db_session: AsyncSession,
    status: TaskStatus,
) -> Task:
    task_body = await _create_task(authed_client)
    task = await db_session.get(Task, uuid.UUID(task_body["id"]))
    assert task is not None
    task.status = status
    task.session_id = "sess-old"
    await db_session.flush()
    return task


class TestCleanupRepositories:
    @pytest.mark.parametrize(
        ("status", "expected_code"),
        [(TaskStatus.DONE, 200), (TaskStatus.FAILED, 200), (TaskStatus.IN_PROGRESS, 409)],
    )
    async def test_status_rule(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Any,
        status: TaskStatus,
        expected_code: int,
    ) -> None:
        monkeypatch.setenv("TRACKER_REPOS_ROOT", str(tmp_path))
        task = await _task_in_status(authed_client, db_session, status)
        (tmp_path / task.code / "repo").mkdir(parents=True)

        response = await authed_client.post(f"/tasks/{task.id}/cleanup-repositories")

        assert response.status_code == expected_code, response.text
        cleaned = expected_code == 200
        assert (tmp_path / task.code).exists() is not cleaned
        if cleaned:
            assert response.json()["repo_cleaned_at"] is not None


class TestForgetSession:
    """
    Раздел 5: после очистки контекста и смены LLM-аккаунта реплики прежней
    сессии не попадают в `{{node.llm_output_last_n}}`.
    """

    async def test_clear_context(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        task = await _task_in_status(authed_client, db_session, TaskStatus.FAILED)

        response = await authed_client.post(f"/tasks/{task.id}/clear-context")

        assert response.status_code == 200, response.text
        await db_session.refresh(task)
        assert task.context_cleared_at is not None

    async def test_llm_account_change(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        # После «Вернуть в новые» сессия прежнего прогона ещё сохранена.
        task = await _task_in_status(authed_client, db_session, TaskStatus.NEW)
        account = await make_llm_account(db_session, owner_id=task.created_by)

        response = await authed_client.patch(
            f"/tasks/{task.id}",
            json={"llm_account_id": str(account.id)},
        )

        assert response.status_code == 200, response.text
        await db_session.refresh(task)
        assert task.session_id is None
        assert task.context_cleared_at is not None


class TestClearContext:
    async def test_resets_session_in_failed(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        task = await _task_in_status(authed_client, db_session, TaskStatus.FAILED)

        response = await authed_client.post(f"/tasks/{task.id}/clear-context")

        assert response.status_code == 200, response.text
        assert response.json()["session_id"] is None

    async def test_rejected_outside_failed(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        task = await _task_in_status(authed_client, db_session, TaskStatus.DONE)

        response = await authed_client.post(f"/tasks/{task.id}/clear-context")

        assert response.status_code == 409
        await db_session.refresh(task)
        assert task.session_id == "sess-old"

    async def test_rejected_with_unfinished_node_log(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        task = await _task_in_status(authed_client, db_session, TaskStatus.FAILED)
        db_session.add(
            NodeLog(
                task_id=task.id,
                trigger_type=NodeLogTriggerType.PIPELINE,
                status=NodeLogStatus.AWAITING_DECISION,
            ),
        )
        await db_session.flush()

        response = await authed_client.post(f"/tasks/{task.id}/clear-context")

        assert response.status_code == 409


class TestCreateTaskValidation:
    async def test_code_taken(self, authed_client: AsyncClient) -> None:
        await _create_task(authed_client, code="RR-20001")

        response = await authed_client.post(
            "/tasks",
            json={"code": "RR-20001", "title": "t", "description": "d"},
        )

        assert response.status_code == 409

    @pytest.mark.parametrize(
        ("parent", "use_summary", "expected_code"),
        [("existing", True, 201), ("missing", False, 404), (None, True, 422)],
    )
    async def test_parent_rules(
        self,
        authed_client: AsyncClient,
        parent: str | None,
        use_summary: bool,
        expected_code: int,
    ) -> None:
        parent_id = {
            "existing": (await _create_task(authed_client))["id"],
            "missing": str(uuid.uuid4()),
            None: None,
        }[parent]

        response = await authed_client.post(
            "/tasks",
            json={
                "code": f"RR-{uuid.uuid4().hex[:8]}",
                "title": "t",
                "description": "d",
                "parent_task_id": parent_id,
                "use_parent_summary": use_summary,
            },
        )

        assert response.status_code == expected_code, response.text
        if expected_code == 201:
            assert response.json()["use_parent_summary"] is True


class TestDuplicateTask:
    async def _done_source(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ) -> Task:
        parent = await _create_task(authed_client)
        source_body = await _create_task(authed_client)
        nodes = await _bind_pipeline_with_nodes(authed_client, db_session, source_body, 2)
        await authed_client.patch(
            f"/tasks/{source_body['id']}/nodes/{nodes[1]['id']}",
            json={"is_enabled": False},
        )
        source = await db_session.get(Task, uuid.UUID(source_body["id"]))
        assert source is not None
        library_node = Node(
            created_by=source.created_by,
            name="lib",
            node_type=NodeType.PLAIN_PROMPT,
            prompt_template="x",
            is_library_item=True,
        )
        db_session.add(library_node)
        await db_session.flush()
        db_session.add_all(
            [
                TaskEnvVariable(task_id=source.id, key="API_URL", value_encrypted="зашифровано"),
                TaskLibraryPrompt(
                    task_id=source.id,
                    node_id=library_node.id,
                    added_by=source.created_by,
                    last_run_status=LibraryPromptRunStatus.SUCCESS,
                ),
            ],
        )
        source.status = TaskStatus.DONE
        source.auto_accept_plan = True
        source.session_id = "sess-source"
        source.parent_task_id = uuid.UUID(parent["id"])
        await db_session.flush()
        return source

    async def test_copies_configuration(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        source = await self._done_source(authed_client, db_session)
        repository = await _make_repository(db_session)

        response = await authed_client.post(
            f"/tasks/{source.id}/duplicate",
            json={
                "code": "RR-30001",
                "title": "Копия",
                "description": "d",
                "repositories": [{"repository_id": str(repository.id), "role": "read_write"}],
            },
        )

        assert response.status_code == 201, response.text
        copy = response.json()
        assert copy["status"] == TaskStatus.NEW.value
        assert copy["pipeline_id"] == str(source.pipeline_id)
        assert copy["auto_accept_plan"] is True
        assert copy["session_id"] is None
        assert copy["parent_task_id"] is None
        copy_nodes = (await authed_client.get(f"/tasks/{copy['id']}/nodes")).json()
        assert [node["is_enabled"] for node in copy_nodes] == [True, False]
        prompts = (await authed_client.get(f"/tasks/{copy['id']}/library-prompts")).json()
        assert [prompt["last_run_status"] for prompt in prompts] == ["never_run"]
        copy_id = uuid.UUID(copy["id"])
        variables = (
            await db_session.execute(
                sa.select(TaskEnvVariable.key).where(TaskEnvVariable.task_id == copy_id),
            )
        ).scalars().all()
        assert list(variables) == ["API_URL"]
        [attached] = (await authed_client.get(f"/tasks/{copy['id']}/repositories")).json()
        assert attached["branch_name"] == "feature/RR-30001"

    async def test_archived_pipeline_rejected(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        """Раздел 3.2: архивный пайплайн к новой задаче не привязывается."""
        source = await self._done_source(authed_client, db_session)
        pipeline = await db_session.get(Pipeline, source.pipeline_id)
        assert pipeline is not None
        pipeline.is_archived = True
        await db_session.flush()

        response = await authed_client.post(
            f"/tasks/{source.id}/duplicate",
            json={"code": "RR-30003", "title": "t", "description": "d"},
        )

        assert response.status_code == 409
        assert "архив" in response.json()["error"]["message"]

    async def test_archived_prompts_skipped(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        source = await self._done_source(authed_client, db_session)
        archived = Node(
            created_by=source.created_by,
            name="старый",
            description="в архиве",
            node_type=NodeType.PLAIN_PROMPT,
            prompt_template="x",
            is_library_item=True,
            is_archived=True,
        )
        db_session.add(archived)
        await db_session.flush()
        db_session.add(
            TaskLibraryPrompt(task_id=source.id, node_id=archived.id, added_by=source.created_by),
        )
        await db_session.flush()

        response = await authed_client.post(
            f"/tasks/{source.id}/duplicate",
            json={"code": "RR-30004", "title": "t", "description": "d"},
        )

        assert response.status_code == 201, response.text
        copy_id = response.json()["id"]
        prompts = (await authed_client.get(f"/tasks/{copy_id}/library-prompts")).json()
        assert [prompt["name"] for prompt in prompts] == ["lib"]

    async def test_requires_done(self, authed_client: AsyncClient) -> None:
        source = await _create_task(authed_client)

        response = await authed_client.post(
            f"/tasks/{source['id']}/duplicate",
            json={"code": "RR-30002", "title": "t", "description": "d"},
        )

        assert response.status_code == 409


class TestRemoteControlReconnect:
    async def test_hands_request_to_worker(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
        redis_client: Redis,
    ) -> None:
        task_body = await _create_task_in_status(authed_client, db_session, TaskStatus.PAUSED)
        task_id = uuid.UUID(task_body["id"])

        response = await authed_client.post(f"/tasks/{task_id}/remote-control/reconnect")

        assert response.status_code == 202, response.text
        assert await consume_bridge_reconnect(redis_client, task_id) is True
        task = await db_session.get(Task, task_id, populate_existing=True)
        assert task is not None
        assert task.remote_control_status is RemoteControlStatus.RECONNECTING

    @pytest.mark.parametrize("status", [TaskStatus.NEW, TaskStatus.DONE, TaskStatus.FAILED])
    async def test_requires_active_session(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
        redis_client: Redis,
        status: TaskStatus,
    ) -> None:
        task_body = await _create_task_in_status(authed_client, db_session, status)

        response = await authed_client.post(f"/tasks/{task_body['id']}/remote-control/reconnect")

        assert response.status_code == 409
        assert await consume_bridge_reconnect(redis_client, uuid.UUID(task_body["id"])) is False


class TestTaskEnvVariables:
    async def test_lifecycle(self, authed_client: AsyncClient, db_session: AsyncSession) -> None:
        task_body = await _create_task(authed_client)
        base = f"/tasks/{task_body['id']}/env-variables"

        created = await authed_client.post(base, json={"key": "API_URL", "value": "https://a"})
        assert created.status_code == 201, created.text
        assert created.json() == {"id": created.json()["id"], "key": "API_URL"}
        variable_id = created.json()["id"]
        stored = await db_session.get(TaskEnvVariable, uuid.UUID(variable_id))
        assert stored is not None
        assert stored.value_encrypted != "https://a"

        updated = await authed_client.patch(f"{base}/{variable_id}", json={"value": "https://b"})
        assert updated.status_code == 200
        revealed = await authed_client.get(f"{base}/{variable_id}/reveal")
        assert revealed.json() == {"value": "https://b"}
        assert [item["key"] for item in (await authed_client.get(base)).json()] == ["API_URL"]

        deleted = await authed_client.delete(f"{base}/{variable_id}")
        assert deleted.status_code == 204
        assert (await authed_client.get(base)).json() == []

    @pytest.mark.parametrize(
        ("key", "expected_code"),
        [("api_url", 422), ("1KEY", 422), ("API-URL", 422), ("TOKEN_2", 201)],
    )
    async def test_key_format(
        self,
        authed_client: AsyncClient,
        key: str,
        expected_code: int,
    ) -> None:
        task_body = await _create_task(authed_client)

        response = await authed_client.post(
            f"/tasks/{task_body['id']}/env-variables",
            json={"key": key, "value": "v"},
        )

        assert response.status_code == expected_code

    async def test_duplicate_key(self, authed_client: AsyncClient) -> None:
        task_body = await _create_task(authed_client)
        base = f"/tasks/{task_body['id']}/env-variables"
        await authed_client.post(base, json={"key": "API_URL", "value": "a"})

        response = await authed_client.post(base, json={"key": "API_URL", "value": "b"})

        assert response.status_code == 409

    async def test_done_task_is_read_only(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        task_body = await _create_task_in_status(authed_client, db_session, TaskStatus.DONE)

        response = await authed_client.post(
            f"/tasks/{task_body['id']}/env-variables",
            json={"key": "API_URL", "value": "a"},
        )

        assert response.status_code == 409

    async def test_variable_of_another_task(self, authed_client: AsyncClient) -> None:
        first = await _create_task(authed_client)
        second = await _create_task(authed_client)
        created = await authed_client.post(
            f"/tasks/{first['id']}/env-variables",
            json={"key": "API_URL", "value": "a"},
        )

        response = await authed_client.get(
            f"/tasks/{second['id']}/env-variables/{created.json()['id']}/reveal",
        )

        assert response.status_code == 404


class TestNodeLogFilters:
    @pytest.mark.parametrize(
        ("params", "expected"),
        [
            ({}, 3),
            ({"status": "failed"}, 1),
            ({"trigger_type": "freeform_manual"}, 1),
            ({"trigger_type": "pipeline", "status": "success"}, 1),
        ],
        ids=["all", "status", "trigger_type", "combined"],
    )
    async def test_filters(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
        params: dict[str, str],
        expected: int,
    ) -> None:
        task_body = await _create_task(authed_client)
        task_id = uuid.UUID(task_body["id"])
        db_session.add_all(
            [
                NodeLog(
                    task_id=task_id,
                    trigger_type=trigger_type,
                    status=status,
                )
                for trigger_type, status in [
                    (NodeLogTriggerType.PIPELINE, NodeLogStatus.SUCCESS),
                    (NodeLogTriggerType.PIPELINE, NodeLogStatus.FAILED),
                    (NodeLogTriggerType.FREEFORM_MANUAL, NodeLogStatus.SUCCESS),
                ]
            ],
        )
        await db_session.flush()

        response = await authed_client.get(f"/tasks/{task_id}/node-logs", params=params)

        assert response.status_code == 200
        assert len(response.json()) == expected

    async def test_node_filter(self, authed_client: AsyncClient, db_session: AsyncSession) -> None:
        task_body = await _create_task(authed_client)
        nodes = await _bind_pipeline_with_nodes(authed_client, db_session, task_body, 2)
        task_id = uuid.UUID(task_body["id"])
        db_session.add_all(
            [
                NodeLog(
                    task_id=task_id,
                    node_id=uuid.UUID(node["node_id"]),
                    trigger_type=NodeLogTriggerType.PIPELINE,
                    status=NodeLogStatus.SUCCESS,
                )
                for node in nodes
            ],
        )
        await db_session.flush()

        response = await authed_client.get(
            f"/tasks/{task_id}/node-logs",
            params={"node_id": nodes[1]["node_id"]},
        )

        assert [entry["node_id"] for entry in response.json()] == [nodes[1]["node_id"]]


class TestActiveSessions:
    async def test_only_own_active_tasks(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
        current_user: User,
    ) -> None:
        other_user = User(email=f"{uuid.uuid4()}@example.com")
        db_session.add(other_user)
        await db_session.flush()
        statuses = [TaskStatus.IN_PROGRESS, TaskStatus.PAUSED, TaskStatus.DONE, TaskStatus.NEW]
        own = [
            Task(
                code=f"RR-{uuid.uuid4().hex[:8]}",
                title=status.value,
                description="d",
                created_by=current_user.id,
                status=status,
            )
            for status in statuses
        ]
        foreign = Task(
            code=f"RR-{uuid.uuid4().hex[:8]}",
            title="чужая",
            description="d",
            created_by=other_user.id,
            status=TaskStatus.IN_PROGRESS,
        )
        db_session.add_all([*own, foreign])
        await db_session.flush()

        response = await authed_client.get("/tasks/active-sessions")

        assert response.status_code == 200
        assert sorted(item["title"] for item in response.json()) == ["in_progress", "paused"]
