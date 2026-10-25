"""`api/nodes.py` — раздел 3.1, 3.2, 5.1, 7.2, 9.5 ТЗ."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest
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
            "description": "Проверка кода перед ревью",
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
            "description": "назначение",
            "node_type": NodeType.PLAIN_PROMPT.value,
            "prompt_template": "{{node.script_output}}",
        },
    )

    assert response.status_code == 422
    assert "node" in response.json()["error"]["message"]


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


async def _pipeline_script_then_consumer(
    db_session: AsyncSession,
    owner_id: uuid.UUID,
) -> tuple[Pipeline, Node, Node]:
    """Скрипт (0) и нода (1), подставляющая его вывод."""
    pipeline = Pipeline(id=uuid.uuid4(), name="P3", created_by=owner_id)
    db_session.add(pipeline)
    await db_session.flush()
    script = Node(
        created_by=owner_id,
        pipeline_id=pipeline.id,
        order_index=0,
        name="Скрипт",
        node_type=NodeType.SCRIPT,
        script_content="echo hi",
        is_library_item=False,
    )
    consumer = Node(
        created_by=owner_id,
        pipeline_id=pipeline.id,
        order_index=1,
        name="Потребитель",
        node_type=NodeType.PLAIN_PROMPT,
        prompt_template="Результат: {{node.script_output}}",
        is_library_item=False,
    )
    db_session.add_all([script, consumer])
    await db_session.flush()
    return pipeline, script, consumer


class TestWholePipelineValidation:
    """Раздел 5.1: после изменения состава пайплайна проверяются все его ноды."""

    async def test_delete_source_rejected(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
        current_user: User,
    ) -> None:
        _pipeline, script, _consumer = await _pipeline_script_then_consumer(
            db_session,
            current_user.id,
        )

        response = await authed_client.delete(f"/nodes/{script.id}")

        assert response.status_code == 422
        assert "Потребитель" in response.json()["error"]["message"]

    async def test_reorder_breaking_reference_rejected(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
        current_user: User,
    ) -> None:
        _pipeline, script, _consumer = await _pipeline_script_then_consumer(
            db_session,
            current_user.id,
        )

        response = await authed_client.patch(f"/nodes/{script.id}", json={"order_index": 5})

        assert response.status_code == 422
        assert "Потребитель" in response.json()["error"]["message"]

    async def test_harmless_change_allowed(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
        current_user: User,
    ) -> None:
        _pipeline, script, _consumer = await _pipeline_script_then_consumer(
            db_session,
            current_user.id,
        )

        response = await authed_client.patch(f"/nodes/{script.id}", json={"name": "Сборка"})

        assert response.status_code == 200

    async def test_insert_before_consumer_allowed(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
        current_user: User,
    ) -> None:
        pipeline, _script, _consumer = await _pipeline_script_then_consumer(
            db_session,
            current_user.id,
        )

        response = await authed_client.post(
            "/nodes",
            json={
                "pipeline_id": str(pipeline.id),
                "order_index": 2,
                "name": "Итог",
                "node_type": NodeType.PLAIN_PROMPT.value,
                "prompt_template": "{{node.llm_output}}",
            },
        )

        assert response.status_code == 201


class TestLibraryDescription:
    """Раздел 3.1, 15.4: описание промта библиотеки обязательно."""

    @pytest.mark.parametrize("description", [None, "", "   "], ids=["missing", "empty", "blank"])
    async def test_create_rejected(
        self,
        authed_client: AsyncClient,
        description: str | None,
    ) -> None:
        response = await authed_client.post(
            "/nodes",
            json={
                "name": "Без описания",
                "description": description,
                "node_type": NodeType.PLAIN_PROMPT.value,
                "prompt_template": "x",
            },
        )

        assert response.status_code == 422
        assert "Описание" in response.json()["error"]["message"]

    async def test_clearing_rejected(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
        current_user: User,
    ) -> None:
        node = Node(
            created_by=current_user.id,
            name="Промт",
            description="было",
            node_type=NodeType.PLAIN_PROMPT,
            prompt_template="x",
            is_library_item=True,
        )
        db_session.add(node)
        await db_session.flush()

        response = await authed_client.patch(f"/nodes/{node.id}", json={"description": " "})

        assert response.status_code == 422

    async def test_legacy_prompt_can_be_archived(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
        current_user: User,
    ) -> None:
        """Промт, заведённый до правила, не застревает: архивация проходит."""
        node = Node(
            created_by=current_user.id,
            name="Старый",
            description=None,
            node_type=NodeType.PLAIN_PROMPT,
            prompt_template="x",
            is_library_item=True,
        )
        db_session.add(node)
        await db_session.flush()

        response = await authed_client.patch(f"/nodes/{node.id}", json={"is_archived": True})

        assert response.status_code == 200
        assert response.json()["is_archived"] is True

    async def test_pipeline_node_without_description(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
        current_user: User,
    ) -> None:
        pipeline = Pipeline(id=uuid.uuid4(), name="P4", created_by=current_user.id)
        db_session.add(pipeline)
        await db_session.flush()

        response = await authed_client.post(
            "/nodes",
            json={
                "pipeline_id": str(pipeline.id),
                "order_index": 0,
                "name": "Шаг",
                "node_type": NodeType.PLAIN_PROMPT.value,
                "prompt_template": "x",
            },
        )

        assert response.status_code == 201


class TestExecutionLimits:
    """Таймаут и retry ноды — в тех же границах, что у «Системных настроек»."""

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("timeout_seconds", 0),
            ("timeout_seconds", 24 * 60 * 60 + 1),
            ("max_retries", 11),
            ("retry_base_delay_seconds", -1),
        ],
    )
    async def test_out_of_range_rejected(
        self,
        authed_client: AsyncClient,
        field: str,
        value: int,
    ) -> None:
        created = await authed_client.post(
            "/nodes",
            json={
                "name": "n",
                "description": "d",
                "node_type": NodeType.PLAIN_PROMPT.value,
                "prompt_template": "x",
            },
        )
        assert created.status_code == 201, created.text
        node_id = created.json()["id"]

        create = await authed_client.post(
            "/nodes",
            json={
                "name": "n",
                "description": "d",
                "node_type": NodeType.PLAIN_PROMPT.value,
                "prompt_template": "x",
                field: value,
            },
        )
        update = await authed_client.patch(f"/nodes/{node_id}", json={field: value})

        assert (create.status_code, update.status_code) == (422, 422)
