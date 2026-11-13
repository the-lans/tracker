"""Категории задач (раздел 15.7 ТЗ): справочник и копирование настроек в задачу."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
import sqlalchemy as sa
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.categories import TaskCategory
from db.models.enums import NodeType, TaskStatus
from db.models.pipelines import Node, Pipeline, TaskNode
from db.models.prompts import TaskLibraryPrompt
from db.models.tasks import DEFAULT_QUEUE_PRIORITY, Task
from db.models.users import User
from services.task_creation import TaskDraft
from services.task_duplication import duplicate_task
from tests.factories import make_pipeline, make_task, make_user, task_code


async def _pipeline_with_nodes(
    db_session: AsyncSession,
    *,
    created_by: uuid.UUID,
    archived: bool = False,
) -> Pipeline:
    pipeline = await make_pipeline(db_session, created_by=created_by)
    pipeline.is_archived = archived
    for order_index, skipped in enumerate((False, True)):
        db_session.add(
            Node(
                pipeline_id=pipeline.id,
                order_index=order_index,
                name=f"Нода {order_index}",
                node_type=NodeType.PLAIN_PROMPT,
                prompt_template="Сделай",
                is_skipped=skipped,
                is_library_item=False,
                created_by=created_by,
            ),
        )
    await db_session.flush()
    return pipeline


async def _library_prompt(
    db_session: AsyncSession,
    *,
    created_by: uuid.UUID,
    name: str = "Ревью",
    archived: bool = False,
) -> Node:
    node = Node(
        name=name,
        node_type=NodeType.PLAIN_PROMPT,
        prompt_template="Проверь код",
        is_library_item=True,
        is_archived=archived,
        created_by=created_by,
    )
    db_session.add(node)
    await db_session.flush()
    return node


async def _create_category(client: AsyncClient, **body: Any) -> dict[str, Any]:
    response = await client.post("/task-categories", json={"name": "Бэкенд", **body})
    assert response.status_code == 201, response.text
    return dict(response.json())


async def _create_task(client: AsyncClient, **body: Any) -> dict[str, Any]:
    payload = {"code": task_code(), "title": "Задача", "description": "Описание", **body}
    response = await client.post("/tasks", json=payload)
    assert response.status_code == 201, response.text
    return dict(response.json())


async def _task_node_flags(db_session: AsyncSession, task_id: str) -> list[bool]:
    stmt = (
        sa.select(TaskNode.is_enabled)
        .where(TaskNode.task_id == uuid.UUID(task_id))
        .order_by(TaskNode.order_index)
    )
    return list((await db_session.execute(stmt)).scalars().all())


async def _task_prompt_ids(db_session: AsyncSession, task_id: str) -> set[uuid.UUID]:
    stmt = sa.select(TaskLibraryPrompt.node_id).where(
        TaskLibraryPrompt.task_id == uuid.UUID(task_id),
    )
    return set((await db_session.execute(stmt)).scalars().all())


class TestCategoryCrud:
    async def test_defaults(self, authed_client: AsyncClient) -> None:
        created = await _create_category(authed_client)

        assert created["name"] == "Бэкенд"
        assert created["pipeline_id"] is None
        assert created["library_prompt_ids"] == []
        assert created["auto_accept_plan"] is False
        assert created["queue_priority"] == DEFAULT_QUEUE_PRIORITY
        assert created["occupies_slot"] is False

    async def test_full_update(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
        current_user: User,
    ) -> None:
        pipeline = await _pipeline_with_nodes(db_session, created_by=current_user.id)
        prompt = await _library_prompt(db_session, created_by=current_user.id)
        created = await _create_category(authed_client)

        response = await authed_client.put(
            f"/task-categories/{created['id']}",
            json={
                "name": "  Фронтенд ",
                "pipeline_id": str(pipeline.id),
                "auto_accept_plan": True,
                "library_prompt_ids": [str(prompt.id), str(prompt.id)],
                "queue_priority": 500,
                "occupies_slot": True,
            },
        )

        assert response.status_code == 200, response.text
        assert response.json() | {"created_at": None, "updated_at": None} == {
            "id": created["id"],
            "name": "Фронтенд",
            "pipeline_id": str(pipeline.id),
            "auto_accept_plan": True,
            "library_prompt_ids": [str(prompt.id)],
            "queue_priority": 500,
            "occupies_slot": True,
            "created_by": str(current_user.id),
            "created_at": None,
            "updated_at": None,
        }

    @pytest.mark.parametrize("name", ["", "   "])
    async def test_empty_name_rejected(self, authed_client: AsyncClient, name: str) -> None:
        response = await authed_client.post("/task-categories", json={"name": name})

        assert response.status_code == 422

    @pytest.mark.parametrize("priority", [0, 1_000_001])
    async def test_priority_range(self, authed_client: AsyncClient, priority: int) -> None:
        response = await authed_client.post(
            "/task-categories",
            json={"name": "Бэкенд", "queue_priority": priority},
        )

        assert response.status_code == 422

    async def test_name_unique_per_owner(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        other = await make_user(db_session)
        db_session.add(TaskCategory(name="Бэкенд", created_by=other.id))
        await db_session.flush()
        await _create_category(authed_client)

        response = await authed_client.post("/task-categories", json={"name": "Бэкенд"})

        assert response.status_code == 409

    async def test_list_only_own_even_for_admin(
        self,
        admin_client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        other = await make_user(db_session)
        db_session.add(TaskCategory(name="Чужая", created_by=other.id))
        await db_session.flush()
        await _create_category(admin_client, name="Своя")

        own = await admin_client.get("/task-categories")
        of_author = await admin_client.get("/task-categories", params={"author_id": str(other.id)})

        assert [item["name"] for item in own.json()] == ["Своя"]
        assert [item["name"] for item in of_author.json()] == ["Чужая"]

    async def test_user_cannot_list_other_author(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        other = await make_user(db_session)

        response = await authed_client.get("/task-categories", params={"author_id": str(other.id)})

        assert response.status_code == 403

    @pytest.mark.parametrize("method", ["put", "delete"])
    async def test_foreign_category_not_found(
        self,
        admin_client: AsyncClient,
        db_session: AsyncSession,
        method: str,
    ) -> None:
        other = await make_user(db_session)
        category = TaskCategory(name="Чужая", created_by=other.id)
        db_session.add(category)
        await db_session.flush()

        response = await admin_client.request(
            method.upper(),
            f"/task-categories/{category.id}",
            json={"name": "Моя"} if method == "put" else None,
        )

        assert response.status_code == 404

    @pytest.mark.parametrize(
        ("field", "status_code"),
        [
            ("archived_pipeline", 409),
            ("foreign_pipeline", 404),
            ("empty_pipeline", 422),
            ("archived_prompt", 409),
        ],
    )
    async def test_rejected_references(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
        current_user: User,
        field: str,
        status_code: int,
    ) -> None:
        other = await make_user(db_session)
        body: dict[str, Any] = {"name": "Бэкенд"}
        if field == "archived_pipeline":
            pipeline = await _pipeline_with_nodes(
                db_session,
                created_by=current_user.id,
                archived=True,
            )
            body["pipeline_id"] = str(pipeline.id)
        elif field == "foreign_pipeline":
            pipeline = await _pipeline_with_nodes(db_session, created_by=other.id)
            body["pipeline_id"] = str(pipeline.id)
        elif field == "empty_pipeline":
            pipeline = await make_pipeline(db_session, created_by=current_user.id)
            body["pipeline_id"] = str(pipeline.id)
        else:
            prompt = await _library_prompt(db_session, created_by=current_user.id, archived=True)
            body["library_prompt_ids"] = [str(prompt.id)]

        response = await authed_client.post("/task-categories", json=body)

        assert response.status_code == status_code

    async def test_archived_choice_kept_on_update(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
        current_user: User,
    ) -> None:
        pipeline = await _pipeline_with_nodes(db_session, created_by=current_user.id)
        prompt = await _library_prompt(db_session, created_by=current_user.id)
        body = {"pipeline_id": str(pipeline.id), "library_prompt_ids": [str(prompt.id)]}
        created = await _create_category(authed_client, **body)
        pipeline.is_archived = True
        prompt.is_archived = True
        await db_session.flush()

        response = await authed_client.put(
            f"/task-categories/{created['id']}",
            json={"name": "Другое имя", **body},
        )

        assert response.status_code == 200, response.text

    async def test_delete_leaves_tasks_without_category(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        category = await _create_category(authed_client)
        task = await _create_task(authed_client, category_id=category["id"])

        response = await authed_client.delete(f"/task-categories/{category['id']}")

        assert response.status_code == 204
        stored = await db_session.get(Task, uuid.UUID(task["id"]))
        assert stored is not None
        await db_session.refresh(stored)
        assert stored.category_id is None


class TestNewTaskOfCategory:
    async def test_settings_copied(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
        current_user: User,
    ) -> None:
        pipeline = await _pipeline_with_nodes(db_session, created_by=current_user.id)
        prompt = await _library_prompt(db_session, created_by=current_user.id)
        archived = await _library_prompt(
            db_session,
            created_by=current_user.id,
            name="Старый",
        )
        category = await _create_category(
            authed_client,
            pipeline_id=str(pipeline.id),
            auto_accept_plan=True,
            library_prompt_ids=[str(prompt.id), str(archived.id)],
            queue_priority=700,
            occupies_slot=True,
        )
        archived.is_archived = True
        await db_session.flush()

        task = await _create_task(authed_client, category_id=category["id"])

        assert task["category_id"] == category["id"]
        assert task["pipeline_id"] == str(pipeline.id)
        assert task["auto_accept_plan"] is True
        assert task["queue_priority"] == 700
        assert task["occupies_slot"] is True
        # «Пропуск по умолчанию» второй ноды переносится в снимок.
        assert await _task_node_flags(db_session, task["id"]) == [True, False]
        assert await _task_prompt_ids(db_session, task["id"]) == {prompt.id}

    async def test_without_category(self, authed_client: AsyncClient) -> None:
        task = await _create_task(authed_client)

        assert task["category_id"] is None
        assert task["pipeline_id"] is None
        assert task["queue_priority"] == DEFAULT_QUEUE_PRIORITY

    async def test_category_without_pipeline(self, authed_client: AsyncClient) -> None:
        category = await _create_category(authed_client, queue_priority=300)

        task = await _create_task(authed_client, category_id=category["id"])

        assert task["pipeline_id"] is None
        assert task["queue_priority"] == 300

    async def test_archived_pipeline_conflict(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
        current_user: User,
    ) -> None:
        pipeline = await _pipeline_with_nodes(db_session, created_by=current_user.id)
        category = await _create_category(authed_client, pipeline_id=str(pipeline.id))
        pipeline.is_archived = True
        await db_session.flush()
        code = task_code()

        response = await authed_client.post(
            "/tasks",
            json={"code": code, "title": "t", "description": "d", "category_id": category["id"]},
        )

        assert response.status_code == 409
        assert "в архиве" in response.json()["error"]["message"]
        assert await db_session.scalar(sa.select(Task.id).where(Task.code == code)) is None

    async def test_emptied_pipeline_rejected(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
        current_user: User,
    ) -> None:
        pipeline = await _pipeline_with_nodes(db_session, created_by=current_user.id)
        category = await _create_category(authed_client, pipeline_id=str(pipeline.id))
        await db_session.execute(sa.delete(Node).where(Node.pipeline_id == pipeline.id))
        code = task_code()

        response = await authed_client.post(
            "/tasks",
            json={"code": code, "title": "t", "description": "d", "category_id": category["id"]},
        )

        assert response.status_code == 422
        assert "нет нод" in response.json()["error"]["message"]
        assert await db_session.scalar(sa.select(Task.id).where(Task.code == code)) is None

    async def test_foreign_category_rejected(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        other = await make_user(db_session)
        category = TaskCategory(name="Чужая", created_by=other.id)
        db_session.add(category)
        await db_session.flush()

        response = await authed_client.post(
            "/tasks",
            json={
                "code": task_code(),
                "title": "t",
                "description": "d",
                "category_id": str(category.id),
            },
        )

        assert response.status_code == 404


class TestChangeTaskCategory:
    async def test_pipeline_copied_when_empty(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
        current_user: User,
    ) -> None:
        pipeline = await _pipeline_with_nodes(db_session, created_by=current_user.id)
        category = await _create_category(
            authed_client,
            pipeline_id=str(pipeline.id),
            queue_priority=900,
        )
        task = await _create_task(authed_client)

        response = await authed_client.patch(
            f"/tasks/{task['id']}",
            json={"category_id": category["id"]},
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["category_id"] == category["id"]
        assert body["pipeline_id"] == str(pipeline.id)
        # Остальные настройки у задачи уже свои — не копируются.
        assert body["queue_priority"] == DEFAULT_QUEUE_PRIORITY

    async def test_own_pipeline_kept(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
        current_user: User,
    ) -> None:
        own = await _pipeline_with_nodes(db_session, created_by=current_user.id)
        other = await _pipeline_with_nodes(db_session, created_by=current_user.id)
        category = await _create_category(authed_client, pipeline_id=str(other.id))
        first = await _create_category(authed_client, name="Своя", pipeline_id=str(own.id))
        task = await _create_task(authed_client, category_id=first["id"])

        response = await authed_client.patch(
            f"/tasks/{task['id']}",
            json={"category_id": category["id"]},
        )

        assert response.json()["pipeline_id"] == str(own.id)

    @pytest.mark.parametrize(
        ("status", "pipeline_copied"),
        [(TaskStatus.NEW, True), (TaskStatus.IN_PROGRESS, False), (TaskStatus.DONE, False)],
    )
    async def test_any_status(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
        current_user: User,
        status: TaskStatus,
        pipeline_copied: bool,
    ) -> None:
        pipeline = await _pipeline_with_nodes(db_session, created_by=current_user.id)
        category = await _create_category(authed_client, pipeline_id=str(pipeline.id))
        task = await make_task(db_session, created_by=current_user.id, status=status)

        response = await authed_client.patch(
            f"/tasks/{task.id}",
            json={"category_id": category["id"]},
        )

        assert response.status_code == 200, response.text
        assert response.json()["category_id"] == category["id"]
        assert (response.json()["pipeline_id"] is not None) is pipeline_copied

    async def test_cleared(self, authed_client: AsyncClient) -> None:
        category = await _create_category(authed_client)
        task = await _create_task(authed_client, category_id=category["id"])

        response = await authed_client.patch(f"/tasks/{task['id']}", json={"category_id": None})

        assert response.json()["category_id"] is None

    async def test_admin_uses_author_category(
        self,
        admin_client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        author = await make_user(db_session)
        author_category = TaskCategory(name="Автора", created_by=author.id)
        db_session.add(author_category)
        await db_session.flush()
        admin_category = await _create_category(admin_client, name="Админа")
        task = await make_task(db_session, created_by=author.id)

        foreign = await admin_client.patch(
            f"/tasks/{task.id}",
            json={"category_id": admin_category["id"]},
        )
        own = await admin_client.patch(
            f"/tasks/{task.id}",
            json={"category_id": str(author_category.id)},
        )

        assert foreign.status_code == 404
        assert own.status_code == 200


class TestDuplicateKeepsCategory:
    @pytest.mark.parametrize("by_author", [True, False])
    async def test_category_of_author(
        self,
        db_session: AsyncSession,
        by_author: bool,
    ) -> None:
        author = await make_user(db_session)
        category = TaskCategory(name="Бэкенд", created_by=author.id)
        db_session.add(category)
        await db_session.flush()
        source = await make_task(
            db_session,
            created_by=author.id,
            status=TaskStatus.DONE,
            category_id=category.id,
        )
        duplicated_by = author.id if by_author else (await make_user(db_session)).id

        copy = await duplicate_task(
            db_session,
            source=source,
            draft=TaskDraft(code=task_code(), title="t", description="d"),
            created_by=duplicated_by,
        )

        assert copy.category_id == (category.id if by_author else None)
