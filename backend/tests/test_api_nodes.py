"""`api/nodes.py` — раздел 3.1, 3.2, 5.1, 7.2, 9.5 ТЗ."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

from db.models.enums import NodeType
from db.models.pipelines import Node, Pipeline
from db.models.prompts import TaskLibraryPrompt
from db.models.tasks import Task
from db.models.users import User

if TYPE_CHECKING:
    from httpx import AsyncClient


async def test_create_library_prompt(authed_client: AsyncClient) -> None:
    response = await authed_client.post(
        "/nodes",
        json={
            "name": "Ревью PR",
            "node_type": NodeType.PLAIN_PROMPT.value,
            "prompt_template": "Проверь код на соответствие стандартам",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["is_library_item"] is True
    assert body["pipeline_id"] is None


async def test_library_prompt_rejects_clear_context_type(authed_client: AsyncClient) -> None:
    response = await authed_client.post(
        "/nodes",
        json={"name": "Очистка", "node_type": NodeType.CLEAR_CONTEXT.value},
    )

    assert response.status_code == 422


async def test_plan_prompt_outside_pipeline_is_rejected(authed_client: AsyncClient) -> None:
    response = await authed_client.post(
        "/nodes",
        json={"name": "План", "node_type": NodeType.PLAN_PROMPT.value},
    )

    assert response.status_code == 422


async def test_library_prompt_rejects_node_variables(authed_client: AsyncClient) -> None:
    response = await authed_client.post(
        "/nodes",
        json={
            "name": "Ссылается на предыдущую ноду",
            "node_type": NodeType.PLAIN_PROMPT.value,
            "prompt_template": "{{node.script_output}}",
        },
    )

    assert response.status_code == 422


async def test_pipeline_node_rejects_unknown_task_variable(
    authed_client: AsyncClient,
    db_session: AsyncSession,
    current_user: User,
) -> None:
    pipeline = Pipeline(id=uuid.uuid4(), name="P", created_by=current_user.id)
    db_session.add(pipeline)
    await db_session.flush()

    response = await authed_client.post(
        "/nodes",
        json={
            "pipeline_id": str(pipeline.id),
            "order_index": 0,
            "name": "N",
            "node_type": NodeType.PLAIN_PROMPT.value,
            "prompt_template": "{{task.not_a_real_field}}",
        },
    )

    assert response.status_code == 422


async def test_pipeline_node_allows_script_output_after_script_node(
    authed_client: AsyncClient,
    db_session: AsyncSession,
    current_user: User,
) -> None:
    pipeline = Pipeline(id=uuid.uuid4(), name="P2", created_by=current_user.id)
    db_session.add(pipeline)
    await db_session.flush()
    db_session.add(
        Node(
            created_by=current_user.id,
            pipeline_id=pipeline.id,
            order_index=0,
            name="Скрипт",
            node_type=NodeType.SCRIPT,
            script_content="echo hi",
            is_library_item=False,
        ),
    )
    await db_session.flush()

    response = await authed_client.post(
        "/nodes",
        json={
            "pipeline_id": str(pipeline.id),
            "order_index": 1,
            "name": "Использует вывод скрипта",
            "node_type": NodeType.PLAIN_PROMPT.value,
            "prompt_template": "Результат: {{node.script_output}}",
        },
    )

    assert response.status_code == 201


async def test_delete_library_prompt_used_by_task_is_rejected(
    authed_client: AsyncClient,
    db_session: AsyncSession,
    current_user: User,
) -> None:
    node = Node(
        created_by=current_user.id,
        name="Используемый промт",
        node_type=NodeType.PLAIN_PROMPT,
        prompt_template="x",
        is_library_item=True,
    )
    db_session.add(node)
    await db_session.flush()
    task = Task(
        id=uuid.uuid4(),
        code=f"RR-{uuid.uuid4().hex[:8]}",
        title="t",
        description="",
        created_by=current_user.id,
    )
    db_session.add(task)
    await db_session.flush()
    db_session.add(TaskLibraryPrompt(task_id=task.id, node_id=node.id, added_by=current_user.id))
    await db_session.flush()

    response = await authed_client.delete(f"/nodes/{node.id}")

    assert response.status_code == 409


class TestLibraryUsage:
    async def test_counts_distinct_tasks(
        self,
        admin_client: AsyncClient,
        db_session: AsyncSession,
        admin_user: User,
    ) -> None:
        used = Node(
            created_by=admin_user.id,
            name="Используемый",
            node_type=NodeType.PLAIN_PROMPT,
            prompt_template="x",
            is_library_item=True,
        )
        unused = Node(
            created_by=admin_user.id,
            name="Свободный",
            node_type=NodeType.PLAIN_PROMPT,
            prompt_template="x",
            is_library_item=True,
        )
        db_session.add_all([used, unused])
        tasks = [
            Task(
                id=uuid.uuid4(),
                code=f"RR-{uuid.uuid4().hex[:8]}",
                title="t",
                description="",
                created_by=admin_user.id,
            )
            for _ in range(2)
        ]
        db_session.add_all(tasks)
        await db_session.flush()
        db_session.add_all(
            [
                TaskLibraryPrompt(task_id=task.id, node_id=used.id, added_by=admin_user.id)
                for task in tasks
            ],
        )
        await db_session.flush()

        response = await admin_client.get("/nodes/library-usage")

        assert response.status_code == 200
        counts = {item["node_id"]: item["task_count"] for item in response.json()}
        assert counts[str(used.id)] == 2
        assert str(unused.id) not in counts

    async def test_admin_only(self, authed_client: AsyncClient) -> None:
        assert (await authed_client.get("/nodes/library-usage")).status_code == 403
