"""`POST /templates/preview` (раздел 5.1 ТЗ)."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

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
