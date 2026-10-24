"""
Смена пайплайна и возврат в `new` (раздел 13.1, 14.2 ТЗ, решение №19 плана):
до запуска пайплайн меняется свободно, после запуска — только через «Вернуть
в новые» из `failed`/`done`; нода попадает в снимок задачи не больше одного раза.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

import pytest
import sqlalchemy as sa

from db.models.enums import TaskStatus
from db.models.pipelines import TaskNode
from db.models.tasks import Task
from tests.factories import make_llm_account

if TYPE_CHECKING:
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession

    from db.models.users import User


async def _pipeline(client: AsyncClient, name: str) -> str:
    pipeline = (await client.post("/pipelines", json={"name": name})).json()
    node = await client.post(
        "/nodes",
        json={
            "pipeline_id": pipeline["id"],
            "order_index": 0,
            "name": f"{name}-node",
            "node_type": "plain_prompt",
            "prompt_template": "шаг",
        },
    )
    assert node.status_code == 201, node.text
    pipeline_id: str = pipeline["id"]
    return pipeline_id


async def _task(client: AsyncClient) -> dict[str, Any]:
    response = await client.post(
        "/tasks",
        json={"code": f"RR-{uuid.uuid4().hex[:6]}", "title": "t", "description": "d"},
    )
    body: dict[str, Any] = response.json()
    return body


async def _node_names(client: AsyncClient, task_id: str) -> list[str]:
    return [node["name"] for node in (await client.get(f"/tasks/{task_id}/nodes")).json()]


class TestChangePipeline:
    async def test_new_pipeline_replaces_snapshot(self, authed_client: AsyncClient) -> None:
        first, second = await _pipeline(authed_client, "A"), await _pipeline(authed_client, "B")
        task = await _task(authed_client)

        await authed_client.post(f"/tasks/{task['id']}/pipeline", json={"pipeline_id": first})
        response = await authed_client.post(
            f"/tasks/{task['id']}/pipeline",
            json={"pipeline_id": second},
        )

        assert response.status_code == 200
        assert response.json()["pipeline_id"] == second
        assert await _node_names(authed_client, task["id"]) == ["B-node"]

    async def test_same_pipeline_twice_no_duplicates(self, authed_client: AsyncClient) -> None:
        pipeline = await _pipeline(authed_client, "A")
        task = await _task(authed_client)

        for _ in range(2):
            await authed_client.post(
                f"/tasks/{task['id']}/pipeline",
                json={"pipeline_id": pipeline},
            )

        assert await _node_names(authed_client, task["id"]) == ["A-node"]

    async def test_snapshot_rejects_duplicate_node(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        pipeline = await _pipeline(authed_client, "A")
        task = await _task(authed_client)
        await authed_client.post(f"/tasks/{task['id']}/pipeline", json={"pipeline_id": pipeline})
        existing = await db_session.scalar(
            sa.select(TaskNode).where(TaskNode.task_id == uuid.UUID(task["id"])),
        )
        assert existing is not None

        db_session.add(
            TaskNode(task_id=existing.task_id, node_id=existing.node_id, order_index=1),
        )
        with pytest.raises(sa.exc.IntegrityError):
            await db_session.flush()


class TestResetToNew:
    @pytest.mark.parametrize("status", [TaskStatus.FAILED, TaskStatus.DONE])
    async def test_reset_then_change_pipeline(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
        status: TaskStatus,
    ) -> None:
        first, second = await _pipeline(authed_client, "A"), await _pipeline(authed_client, "B")
        body = await _task(authed_client)
        await authed_client.post(f"/tasks/{body['id']}/pipeline", json={"pipeline_id": first})
        task = await db_session.get(Task, uuid.UUID(body["id"]))
        assert task is not None
        task.status = status
        task.last_failed_order_index = 0
        task.auto_start_enabled = True
        await db_session.flush()

        rejected = await authed_client.post(
            f"/tasks/{body['id']}/pipeline",
            json={"pipeline_id": second},
        )
        reset = await authed_client.post(f"/tasks/{body['id']}/reset")
        changed = await authed_client.post(
            f"/tasks/{body['id']}/pipeline",
            json={"pipeline_id": second},
        )

        assert rejected.status_code == 422
        assert reset.status_code == 200
        assert reset.json()["status"] == "new"
        assert reset.json()["last_failed_order_index"] is None
        assert reset.json()["auto_start_enabled"] is False
        assert changed.status_code == 200
        assert await _node_names(authed_client, body["id"]) == ["B-node"]

    @pytest.mark.parametrize(
        "status",
        [TaskStatus.NEW, TaskStatus.QUEUED, TaskStatus.IN_PROGRESS, TaskStatus.PAUSED],
    )
    async def test_live_or_new_task_not_reset(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
        status: TaskStatus,
    ) -> None:
        body = await _task(authed_client)
        task = await db_session.get(Task, uuid.UUID(body["id"]))
        assert task is not None
        task.status = status
        await db_session.flush()

        response = await authed_client.post(f"/tasks/{body['id']}/reset")

        assert response.status_code == 409


class TestAccountChangeAfterReset:
    """
    Сессия хранится в каталоге своего LLM-аккаунта (раздел 19.5): после
    смены аккаунта прежний `session_id` не продолжить.
    """

    @pytest.mark.parametrize(("switch", "session_kept"), [(True, False), (False, True)])
    async def test_session_forgotten_only_on_switch(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
        current_user: User,
        switch: bool,
        session_kept: bool,
    ) -> None:
        first = await make_llm_account(db_session, owner_id=current_user.id)
        second = await make_llm_account(db_session, owner_id=current_user.id)
        body = await _task(authed_client)
        task = await db_session.get(Task, uuid.UUID(body["id"]))
        assert task is not None
        task.llm_account_id = first.id
        task.session_id = "sess-old"
        await db_session.flush()

        chosen = second if switch else first
        response = await authed_client.patch(
            f"/tasks/{body['id']}",
            json={"llm_account_id": str(chosen.id)},
        )

        assert response.status_code == 200, response.text
        await db_session.refresh(task)
        assert (task.session_id == "sess-old") is session_kept

