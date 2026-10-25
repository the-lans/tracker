"""`POST /templates/preview` (раздел 5.1 ТЗ)."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.enums import NodeType
from db.models.pipelines import Node, Pipeline
from db.models.tasks import Task
from db.models.users import User
from services.templating import RenderScope

if TYPE_CHECKING:
    from httpx import AsyncClient


async def test_preview_without_task_validates_and_echoes_text(authed_client: AsyncClient) -> None:
    response = await authed_client.post(
        "/templates/preview",
        json={"text": "Заголовок задачи: {{task.title}}", "scope": RenderScope.FREEFORM.value},
    )

    assert response.status_code == 200
    assert response.json()["rendered_text"] == "Заголовок задачи: {{task.title}}"


async def test_preview_without_task_rejects_unknown_variable(authed_client: AsyncClient) -> None:
    response = await authed_client.post(
        "/templates/preview",
        json={"text": "{{task.not_a_field}}", "scope": RenderScope.FREEFORM.value},
    )

    assert response.status_code == 422


async def test_preview_with_task_renders_real_value(
    authed_client: AsyncClient,
    db_session: AsyncSession,
    current_user: User,
) -> None:
    task = Task(
        id=uuid.uuid4(),
        code=f"RR-{uuid.uuid4().hex[:8]}",
        title="Реальный заголовок",
        description="",
        created_by=current_user.id,
    )
    db_session.add(task)
    await db_session.flush()

    response = await authed_client.post(
        "/templates/preview",
        json={
            "text": "Заголовок: {{task.title}}",
            "scope": RenderScope.FREEFORM.value,
            "task_id": str(task.id),
        },
    )

    assert response.status_code == 200
    assert response.json()["rendered_text"] == "Заголовок: Реальный заголовок"


async def test_preview_rejects_node_variables_in_freeform_scope(authed_client: AsyncClient) -> None:
    response = await authed_client.post(
        "/templates/preview",
        json={"text": "{{node.script_output}}", "scope": RenderScope.FREEFORM.value},
    )

    assert response.status_code == 422


class TestFreeformPreviewSlashCommand:
    async def test_returned_verbatim(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
        current_user: User,
    ) -> None:
        task = Task(
            id=uuid.uuid4(),
            code=f"RR-{uuid.uuid4().hex[:8]}",
            title="t",
            description="",
            created_by=current_user.id,
        )
        db_session.add(task)
        await db_session.flush()

        response = await authed_client.post(
            "/templates/preview",
            json={
                "text": "/review {{task.title}}",
                "scope": RenderScope.FREEFORM.value,
                "task_id": str(task.id),
            },
        )

        assert response.status_code == 200
        assert response.json()["rendered_text"] == "/review {{task.title}}"


class TestPipelineNodePreview:
    """Раздел 5.1: предпросмотр ноды пайплайна видит предыдущие ноды, как сохранение."""

    async def _pipeline_with_prompt(self, db_session: AsyncSession, user: User) -> Pipeline:
        pipeline = Pipeline(name="пайплайн", created_by=user.id)
        db_session.add(pipeline)
        await db_session.flush()
        db_session.add(
            Node(
                created_by=user.id,
                pipeline_id=pipeline.id,
                order_index=0,
                name="промт",
                node_type=NodeType.PLAIN_PROMPT,
                prompt_template="Сделай",
                is_library_item=False,
            ),
        )
        await db_session.flush()
        return pipeline

    @pytest.mark.parametrize(("order_index", "status"), [(1, 200), (0, 422)])
    async def test_new_node_position(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
        current_user: User,
        order_index: int,
        status: int,
    ) -> None:
        pipeline = await self._pipeline_with_prompt(db_session, current_user)

        response = await authed_client.post(
            "/templates/preview",
            json={
                "text": "Итог: {{node.llm_output}}",
                "scope": RenderScope.PIPELINE.value,
                "pipeline_id": str(pipeline.id),
                "order_index": order_index,
            },
        )

        assert response.status_code == status, response.text

    async def test_saved_node(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
        current_user: User,
    ) -> None:
        pipeline = await self._pipeline_with_prompt(db_session, current_user)
        node = Node(
            created_by=current_user.id,
            pipeline_id=pipeline.id,
            order_index=1,
            name="итоги",
            node_type=NodeType.PLAIN_PROMPT,
            prompt_template="{{node.llm_output_last_n}}",
            is_library_item=False,
            llm_output_last_n=2,
        )
        db_session.add(node)
        await db_session.flush()

        response = await authed_client.post(
            "/templates/preview",
            json={
                "text": "{{node.llm_output_last_n}}",
                "scope": RenderScope.PIPELINE.value,
                "node_id": str(node.id),
            },
        )

        assert response.status_code == 200, response.text
