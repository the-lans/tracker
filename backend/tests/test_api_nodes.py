"""`api/nodes.py` — раздел 3.1, 3.2, 5.1, 7.2, 9.5 ТЗ."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.enums import NodeType
from db.models.pipelines import Node, Pipeline, TaskNode
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
    assert body["pause_after"] is False


class TestPipelinePause:
    async def test_pause_can_be_set_on_create(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
        current_user: User,
    ) -> None:
        pipeline = Pipeline(name="p", created_by=current_user.id)
        db_session.add(pipeline)
        await db_session.flush()

        response = await authed_client.post(
            "/nodes",
            json={
                "pipeline_id": str(pipeline.id),
                "order_index": 0,
                "name": "n",
                "node_type": "plain_prompt",
                "prompt_template": "p",
                "pause_after": True,
            },
        )

        assert response.status_code == 201, response.text
        assert response.json()["pause_after"] is True

    @pytest.mark.parametrize("pipeline_node", [False, True])
    async def test_pause_rejected_outside_pipeline_or_after_clear_context(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
        current_user: User,
        pipeline_node: bool,
    ) -> None:
        fields: dict[str, object] = {
            "name": "n",
            "description": "d",
            "node_type": "plain_prompt",
            "prompt_template": "p",
            "pause_after": True,
        }
        if pipeline_node:
            pipeline = Pipeline(name="p", created_by=current_user.id)
            db_session.add(pipeline)
            await db_session.flush()
            fields.update(pipeline_id=str(pipeline.id), order_index=0, node_type="clear_context")

        response = await authed_client.post("/nodes", json=fields)

        assert response.status_code == 422, response.text


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


class TestSystemExecutionSettings:
    async def test_legacy_overrides_not_exposed(
        self,
        authed_client: AsyncClient,
    ) -> None:
        legacy = {"timeout_seconds": 1800, "max_retries": 7, "retry_base_delay_seconds": 30}
        response = await authed_client.post(
            "/nodes",
            json={
                "name": "n",
                "description": "d",
                "node_type": "plain_prompt",
                "prompt_template": "x",
                **legacy,
            },
        )
        assert response.status_code == 201, response.text
        assert not legacy.keys() & response.json().keys()
        updated = await authed_client.patch(
            f"/nodes/{response.json()['id']}",
            json={"name": "renamed", **legacy},
        )
        assert updated.status_code == 200, updated.text
        assert not legacy.keys() & updated.json().keys()


def _library_prompt(**fields: object) -> dict[str, object]:
    return {
        "name": "n",
        "description": "d",
        "node_type": NodeType.PLAIN_PROMPT.value,
        "prompt_template": "x",
        **fields,
    }


class TestReasoningEffort:
    """Раздел 3.1 `nodes.reasoning_effort`: уровень ноды или по умолчанию аккаунта."""

    async def test_kept_until_cleared(self, authed_client: AsyncClient) -> None:
        created = await authed_client.post("/nodes", json=_library_prompt(reasoning_effort="max"))
        assert created.status_code == 201, created.text
        node_id = created.json()["id"]

        renamed = await authed_client.patch(f"/nodes/{node_id}", json={"name": "m"})
        cleared = await authed_client.patch(f"/nodes/{node_id}", json={"reasoning_effort": None})

        assert created.json()["reasoning_effort"] == "max"
        assert renamed.json()["reasoning_effort"] == "max"
        assert cleared.json()["reasoning_effort"] is None

    @pytest.mark.parametrize(
        "payload",
        [
            {
                "name": "s",
                "description": "d",
                "node_type": NodeType.SCRIPT.value,
                "script_language": "bash",
                "script_content": "true",
                "reasoning_effort": "low",
            },
            _library_prompt(reasoning_effort="extreme"),
        ],
        ids=["script", "unknown_level"],
    )
    async def test_rejected(self, authed_client: AsyncClient, payload: dict[str, object]) -> None:
        response = await authed_client.post("/nodes", json=payload)

        assert response.status_code == 422


async def _own_pipeline(db_session: AsyncSession, user: User) -> Pipeline:
    pipeline = Pipeline(id=uuid.uuid4(), name="P", created_by=user.id)
    db_session.add(pipeline)
    await db_session.flush()
    return pipeline


async def _library_item(db_session: AsyncSession, owner: User, **fields: object) -> Node:
    values: dict[str, object] = {
        "created_by": owner.id,
        "name": "Ревью",
        "description": "d",
        "node_type": NodeType.PLAIN_PROMPT,
        "prompt_template": "Проверь $1",
        "is_library_item": True,
        **fields,
    }
    node = Node(**values)
    db_session.add(node)
    await db_session.flush()
    return node


def _linked_node(pipeline: Pipeline, library_node: Node, **fields: object) -> dict[str, object]:
    return {
        "pipeline_id": str(pipeline.id),
        "order_index": 0,
        "name": "Шаг",
        "node_type": NodeType.PLAIN_PROMPT.value,
        "library_node_id": str(library_node.id),
        **fields,
    }


class TestLibraryLink:
    """Раздел 7.6: нода пайплайна со ссылкой на промт библиотеки."""

    @pytest.mark.parametrize("plan_mode", [False, True])
    async def test_linked_source_type_is_locked(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
        current_user: User,
        plan_mode: bool,
    ) -> None:
        pipeline = await _own_pipeline(db_session, current_user)
        source = await _library_item(db_session, current_user)
        response = await authed_client.post(
            "/nodes",
            json=_linked_node(pipeline, source, library_plan_mode=plan_mode),
        )
        assert response.status_code == 201, response.text
        response = await authed_client.patch(
            f"/nodes/{source.id}",
            json={"node_type": "script", "script_language": "bash", "script_content": "echo ok"},
        )
        assert response.status_code == 409, response.text
        await db_session.refresh(source)
        assert source.node_type is NodeType.PLAIN_PROMPT
        response = await authed_client.patch(
            f"/nodes/{source.id}",
            json={"node_type": "plain_prompt", "name": "Новое имя"},
        )
        assert response.status_code == 200, response.text

    async def test_unlinked_source_type_can_change(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
        current_user: User,
    ) -> None:
        source = await _library_item(db_session, current_user)
        response = await authed_client.patch(
            f"/nodes/{source.id}",
            json={"node_type": "script", "script_language": "bash", "script_content": "echo ok"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["node_type"] == "script"

    @pytest.mark.parametrize("plan_mode", [False, True])
    async def test_unlink_library_prompt_to_script(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
        current_user: User,
        plan_mode: bool,
    ) -> None:
        pipeline = await _own_pipeline(db_session, current_user)
        source = await _library_item(db_session, current_user)
        created = await authed_client.post(
            "/nodes",
            json=_linked_node(pipeline, source, library_plan_mode=plan_mode),
        )
        assert created.status_code == 201, created.text
        response = await authed_client.patch(
            f"/nodes/{created.json()['id']}",
            json={
                "library_node_id": None,
                "node_type": "script",
                "script_language": "bash",
                "script_content": "echo ok",
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["node_type"] == "script"
        assert response.json()["library_node_id"] is None

    @pytest.mark.parametrize("source_type", [None, NodeType.SCRIPT, NodeType.SLASH_COMMAND])
    async def test_plan_mode_requires_text_library_prompt(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
        current_user: User,
        source_type: NodeType | None,
    ) -> None:
        pipeline = await _own_pipeline(db_session, current_user)
        body: dict[str, object] = {
            "pipeline_id": str(pipeline.id),
            "order_index": 0,
            "name": "Plan",
            "node_type": "plain_prompt",
            "library_plan_mode": True,
        }
        if source_type is not None:
            source = await _library_item(db_session, current_user, node_type=source_type)
            body["library_node_id"] = str(source.id)
        response = await authed_client.post("/nodes", json=body)
        assert response.status_code == 422, response.text

    async def test_library_plan_mode_can_be_enabled_and_disabled(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
        current_user: User,
    ) -> None:
        pipeline = await _own_pipeline(db_session, current_user)
        source = await _library_item(db_session, current_user)
        response = await authed_client.post(
            "/nodes",
            json=_linked_node(pipeline, source, library_plan_mode=True),
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["library_plan_mode"] is True
        assert body["node_type"] == "plan_prompt"
        assert source.node_type is NodeType.PLAIN_PROMPT
        response = await authed_client.patch(
            f"/nodes/{body['id']}",
            json={"library_arguments": "{{task.code}}"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["library_plan_mode"] is True
        response = await authed_client.patch(
            f"/nodes/{body['id']}",
            json={"library_plan_mode": False},
        )
        assert response.status_code == 200, response.text
        assert response.json()["library_plan_mode"] is False
        assert response.json()["node_type"] == "plain_prompt"

    @pytest.mark.parametrize(
        ("arguments", "status"),
        [
            ("{{task.code}}", 201),
            ("{{task.unknown}}", 422),
            ("{{env.SECRET}}", 422),
            ("{{node.llm_output}}", 422),
            ("{{session.id}}", 422),
            ("{{unknown.code}}", 422),
        ],
    )
    async def test_argument_variables_validated_on_save(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
        current_user: User,
        arguments: str,
        status: int,
    ) -> None:
        pipeline = await _own_pipeline(db_session, current_user)
        source = await _library_item(db_session, current_user)

        response = await authed_client.post(
            "/nodes",
            json=_linked_node(pipeline, source, library_arguments=arguments),
        )

        assert response.status_code == status, response.text
        if status == 201:
            assert response.json()["library_arguments"] == arguments

    async def test_argument_validation_on_update(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
        current_user: User,
    ) -> None:
        pipeline = await _own_pipeline(db_session, current_user)
        source = await _library_item(db_session, current_user)
        created = await authed_client.post("/nodes", json=_linked_node(pipeline, source))
        node_url = f"/nodes/{created.json()['id']}"

        updated = await authed_client.patch(node_url, json={"library_arguments": "{{task.code}}"})
        rejected = await authed_client.patch(node_url, json={"library_arguments": "{{env.SECRET}}"})
        saved = await authed_client.get(node_url)

        assert updated.status_code == 200, updated.text
        assert rejected.status_code == 422, rejected.text
        assert saved.json()["library_arguments"] == "{{task.code}}"

    async def test_link_takes_type_and_drops_own_content(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
        current_user: User,
    ) -> None:
        pipeline = await _own_pipeline(db_session, current_user)
        script = await _library_item(
            db_session,
            current_user,
            node_type=NodeType.SCRIPT,
            prompt_template=None,
            script_language="bash",
            script_content="echo $1",
        )

        response = await authed_client.post(
            "/nodes",
            json=_linked_node(
                pipeline,
                script,
                prompt_template="свой текст",
                library_arguments="'a b' c",
            ),
        )

        assert response.status_code == 201, response.text
        body = response.json()
        assert (body["node_type"], body["prompt_template"], body["library_arguments"]) == (
            "script",
            None,
            "'a b' c",
        )

    @pytest.mark.parametrize(
        ("fields", "status"),
        [
            ({"is_archived": True}, 409),
            ({"node_type": NodeType.CLEAR_CONTEXT, "prompt_template": None}, 422),
            ({"is_library_item": False}, 422),
        ],
        ids=["архивный", "недопустимый-тип", "не-библиотека"],
    )
    async def test_rejected_source(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
        current_user: User,
        fields: dict[str, object],
        status: int,
    ) -> None:
        pipeline = await _own_pipeline(db_session, current_user)
        other = await _own_pipeline(db_session, current_user)
        library_fields = {"pipeline_id": other.id} if fields.get("is_library_item") is False else {}
        source = await _library_item(db_session, current_user, **fields, **library_fields)

        response = await authed_client.post("/nodes", json=_linked_node(pipeline, source))

        assert response.status_code == status, response.text

    async def test_foreign_library_rejected(
        self,
        admin_client: AsyncClient,
        db_session: AsyncSession,
        admin_user: User,
        current_user: User,
    ) -> None:
        pipeline = await _own_pipeline(db_session, admin_user)
        foreign = await _library_item(db_session, current_user)

        response = await admin_client.post("/nodes", json=_linked_node(pipeline, foreign))

        assert response.status_code == 422
        assert "автору пайплайна" in response.json()["error"]["message"]

    async def test_library_item_needs_pipeline(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
        current_user: User,
    ) -> None:
        source = await _library_item(db_session, current_user)

        response = await authed_client.post(
            "/nodes",
            json=_library_prompt(library_node_id=str(source.id)),
        )

        assert response.status_code == 422

    async def test_unlink_keeps_new_text(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
        current_user: User,
    ) -> None:
        pipeline = await _own_pipeline(db_session, current_user)
        source = await _library_item(db_session, current_user)
        created = await authed_client.post("/nodes", json=_linked_node(pipeline, source))

        unlinked = await authed_client.patch(
            f"/nodes/{created.json()['id']}",
            json={"library_node_id": None, "prompt_template": "свой"},
        )

        assert unlinked.status_code == 200, unlinked.text
        assert (unlinked.json()["library_node_id"], unlinked.json()["prompt_template"]) == (
            None,
            "свой",
        )

    async def test_linked_item_not_deletable_but_archivable(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
        current_user: User,
    ) -> None:
        pipeline = await _own_pipeline(db_session, current_user)
        source = await _library_item(db_session, current_user)
        created = await authed_client.post("/nodes", json=_linked_node(pipeline, source))
        assert created.status_code == 201, created.text

        deleted = await authed_client.delete(f"/nodes/{source.id}")
        archived = await authed_client.patch(f"/nodes/{source.id}", json={"is_archived": True})
        renamed = await authed_client.patch(
            f"/nodes/{created.json()['id']}",
            json={"name": "Шаг 1"},
        )

        assert (deleted.status_code, archived.status_code, renamed.status_code) == (409, 200, 200)

    async def test_usage_counts_tasks_running_linked_node(
        self,
        admin_client: AsyncClient,
        db_session: AsyncSession,
        admin_user: User,
    ) -> None:
        pipeline = await _own_pipeline(db_session, admin_user)
        source = await _library_item(db_session, admin_user)
        linking = Node(
            created_by=admin_user.id,
            pipeline_id=pipeline.id,
            name="Шаг",
            node_type=NodeType.PLAIN_PROMPT,
            is_library_item=False,
            library_node_id=source.id,
        )
        task = Task(
            id=uuid.uuid4(),
            code=f"RR-{uuid.uuid4().hex[:8]}",
            title="t",
            description="",
            created_by=admin_user.id,
        )
        db_session.add_all([linking, task])
        await db_session.flush()
        db_session.add(TaskNode(task_id=task.id, node_id=linking.id, order_index=0))
        await db_session.flush()

        response = await admin_client.get("/nodes/library-usage")

        counts = {item["node_id"]: item["task_count"] for item in response.json()}
        assert counts[str(source.id)] == 1


class TestGuideUrl:
    """Раздел 3.1, 5: гайд — только у «Обычного промта»."""

    @pytest.mark.parametrize(
        ("node_type", "expected"),
        [
            (NodeType.PLAIN_PROMPT, "https://wiki.example.com/g"),
            (NodeType.SLASH_COMMAND, None),
        ],
    )
    async def test_kept_only_for_plain_prompt(
        self,
        authed_client: AsyncClient,
        node_type: NodeType,
        expected: str | None,
    ) -> None:
        response = await authed_client.post(
            "/nodes",
            json=_library_prompt(
                node_type=node_type.value,
                command_invocation="/review",
                guide_url="https://wiki.example.com/g",
            ),
        )

        assert response.status_code == 201, response.text
        assert response.json()["guide_url"] == expected

    async def test_cleared_by_null(self, authed_client: AsyncClient) -> None:
        created = await authed_client.post(
            "/nodes",
            json=_library_prompt(guide_url="https://wiki.example.com/g"),
        )

        cleared = await authed_client.patch(
            f"/nodes/{created.json()['id']}",
            json={"guide_url": None},
        )

        assert cleared.json()["guide_url"] is None
