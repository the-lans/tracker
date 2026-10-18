"""`api/pipelines.py` — правило 9 CLAUDE.md/раздел 3.2 ТЗ: удаление вместо
архивации запрещено для пайплайна, используемого хотя бы одной задачей."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

from db.models.pipelines import Pipeline
from db.models.tasks import Task
from db.models.users import User

if TYPE_CHECKING:
    from httpx import AsyncClient


async def test_create_and_get_pipeline(authed_client: AsyncClient) -> None:
    create_response = await authed_client.post("/pipelines", json={"name": "Демо"})
    assert create_response.status_code == 201
    pipeline_id = create_response.json()["id"]

    get_response = await authed_client.get(f"/pipelines/{pipeline_id}")

    assert get_response.status_code == 200
    assert get_response.json()["is_archived"] is False


async def test_list_pipelines_excludes_archived_by_default(authed_client: AsyncClient) -> None:
    create_response = await authed_client.post("/pipelines", json={"name": "Архивный"})
    pipeline_id = create_response.json()["id"]
    await authed_client.patch(f"/pipelines/{pipeline_id}", json={"is_archived": True})

    default_list = await authed_client.get("/pipelines")
    full_list = await authed_client.get("/pipelines", params={"include_archived": "true"})

    assert pipeline_id not in [p["id"] for p in default_list.json()]
    assert pipeline_id in [p["id"] for p in full_list.json()]


async def test_delete_pipeline_used_by_task_is_rejected(
    authed_client: AsyncClient,
    db_session: AsyncSession,
    current_user: User,
) -> None:
    pipeline = Pipeline(id=uuid.uuid4(), name="Используемый")
    db_session.add(pipeline)
    await db_session.flush()
    task = Task(
        id=uuid.uuid4(),
        code=f"RR-{uuid.uuid4().hex[:8]}",
        title="t",
        description="",
        pipeline_id=pipeline.id,
        created_by=current_user.id,
    )
    db_session.add(task)
    await db_session.flush()

    response = await authed_client.delete(f"/pipelines/{pipeline.id}")

    assert response.status_code == 409


async def test_delete_unused_pipeline_succeeds(authed_client: AsyncClient) -> None:
    create_response = await authed_client.post("/pipelines", json={"name": "Неиспользуемый"})
    pipeline_id = create_response.json()["id"]

    response = await authed_client.delete(f"/pipelines/{pipeline_id}")

    assert response.status_code == 204
