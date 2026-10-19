"""Роутер `api/tasks.py` — жизненный цикл задачи (раздел 2.3, 2.4, 7, 8, 9.6 ТЗ)."""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.enums import (
    LibraryPromptRunStatus,
    ManualRequestStatus,
    NodeLogStatus,
    NodeLogTriggerType,
    NodeType,
    RepositoryRole,
    TaskStatus,
)
from db.models.llm import LlmAccount
from db.models.logs import NodeLog
from db.models.pipelines import Node, Pipeline
from db.models.prompts import TaskLibraryPrompt, TaskManualRequestQueue
from db.models.repositories import Repository
from db.models.tasks import Task
from db.models.users import User
from services.plan_mode import PlanDecisionOption, encode_decision
from services.task_signal import wait_for_task_signal

if TYPE_CHECKING:
    from httpx import AsyncClient
    from redis.asyncio import Redis

pytestmark = pytest.mark.usefixtures("redis_container")


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
    pipeline = Pipeline(name="Демо-пайплайн")
    db_session.add(pipeline)
    await db_session.flush()
    node_a = Node(
        pipeline_id=pipeline.id,
        order_index=0,
        name="Шаг 1",
        node_type=NodeType.PLAIN_PROMPT,
        prompt_template="Привет",
        is_library_item=False,
    )
    node_b = Node(
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
    empty_pipeline = Pipeline(name="Пустой пайплайн")
    db_session.add(empty_pipeline)
    await db_session.flush()

    response = await authed_client.post(
        f"/tasks/{task_body['id']}/pipeline",
        json={"pipeline_id": str(empty_pipeline.id)},
    )

    assert response.status_code == 422


async def test_bind_pipeline_rejects_task_not_in_new_status(
    authed_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    task_body = await _create_task(authed_client)
    task = await db_session.get(Task, uuid.UUID(task_body["id"]))
    assert task is not None
    task.status = TaskStatus.DONE
    await db_session.flush()
    pipeline = Pipeline(name="Пайплайн")
    db_session.add(pipeline)
    await db_session.flush()
    db_session.add(
        Node(
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
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task_body = await _create_task(authed_client)
    enqueued_task_ids: list[str] = []
    monkeypatch.setattr(
        "api.tasks.run_task_session",
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
    task_body = await _create_task(authed_client)
    task = await db_session.get(Task, uuid.UUID(task_body["id"]))
    assert task is not None
    task.status = TaskStatus.DONE
    await db_session.flush()
    monkeypatch.setattr("api.tasks.run_task_session", SimpleNamespace(delay=lambda _task_id: None))

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
            status=NodeLogStatus.SUCCESS,
        ),
    )
    await db_session.flush()

    response = await authed_client.get(f"/tasks/{task_body['id']}/node-logs")

    assert response.status_code == 200
    entries = response.json()
    assert len(entries) == 1
    assert entries[0]["status"] == NodeLogStatus.SUCCESS.value


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


async def test_submit_freeform_prompt_enqueues_manual_request(
    authed_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    task_body = await _create_task(authed_client)

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
    task_body = await _create_task(authed_client)
    node = Node(
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
    task_body = await _create_task(authed_client)
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
    task_body = await _create_task(authed_client)
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
    repository = Repository(name=name, git_url="git@example.com:x.git", deploy_key_encrypted="k")
    db_session.add(repository)
    await db_session.flush()
    return repository


async def test_create_task_attaches_repositories_and_llm_account(
    authed_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    repository = await _make_repository(db_session)
    llm_account = LlmAccount(label="main", claude_config_dir="/home/svc/.claude")
    db_session.add(llm_account)
    await db_session.flush()

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
    task_body = await _create_task(authed_client)
    task = await db_session.get(Task, uuid.UUID(task_body["id"]))
    assert task is not None
    task.status = TaskStatus.FAILED
    task.last_failed_order_index = 3
    await db_session.flush()
    calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
    monkeypatch.setattr(
        "api.tasks.run_task_session",
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
    monkeypatch.setattr("api.tasks.run_task_session", SimpleNamespace(delay=None))

    response = await authed_client.post(f"/tasks/{task_body['id']}/restart")

    assert response.status_code == 422
