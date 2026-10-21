"""
Владение записями в API (раздел 19.2 ТЗ, решение №16 плана): `user` видит и
меняет только свои задачи, пайплайны, промты и шаблоны, `admin` — все.
Чужая запись для `user` — 404, как несуществующая.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

import pytest

from db.models.enums import NodeType, TaskStatus
from db.models.pipelines import Node, Pipeline
from db.models.repositories import Repository, Template
from db.models.tasks import Task
from services.crypto import encrypt
from tests.factories import make_user

if TYPE_CHECKING:
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession

    from db.models.users import User


async def _task(
    db_session: AsyncSession,
    owner_id: uuid.UUID,
    *,
    status: TaskStatus = TaskStatus.NEW,
) -> Task:
    task = Task(
        code=f"RR-{uuid.uuid4().hex[:6]}",
        title="t",
        description="d",
        created_by=owner_id,
        status=status,
    )
    db_session.add(task)
    await db_session.flush()
    return task


async def _pipeline_with_node(db_session: AsyncSession, owner_id: uuid.UUID) -> Pipeline:
    pipeline = Pipeline(name=f"p-{uuid.uuid4().hex[:6]}", is_archived=False, created_by=owner_id)
    db_session.add(pipeline)
    await db_session.flush()
    db_session.add(
        Node(
            pipeline_id=pipeline.id,
            order_index=0,
            name="шаг",
            node_type=NodeType.PLAIN_PROMPT,
            prompt_template="x",
            is_library_item=False,
            created_by=owner_id,
        ),
    )
    await db_session.flush()
    return pipeline


async def _library_node(
    db_session: AsyncSession,
    owner_id: uuid.UUID,
    *,
    is_archived: bool = False,
) -> Node:
    node = Node(
        name=f"lib-{uuid.uuid4().hex[:6]}",
        node_type=NodeType.PLAIN_PROMPT,
        prompt_template="x",
        is_library_item=True,
        is_archived=is_archived,
        created_by=owner_id,
    )
    db_session.add(node)
    await db_session.flush()
    return node


async def _template(db_session: AsyncSession, owner_id: uuid.UUID) -> Template:
    template = Template(name=f"tpl-{uuid.uuid4().hex[:6]}", files={}, created_by=owner_id)
    db_session.add(template)
    await db_session.flush()
    return template


class TestTasks:
    async def test_list_shows_only_own(
        self,
        authed_client: AsyncClient,
        current_user: User,
        db_session: AsyncSession,
    ) -> None:
        other = await make_user(db_session)
        own = await _task(db_session, current_user.id)
        foreign = await _task(db_session, other.id)

        ids = {item["id"] for item in (await authed_client.get("/tasks")).json()}

        assert str(own.id) in ids
        assert str(foreign.id) not in ids

    async def test_admin_lists_all(
        self,
        admin_client: AsyncClient,
        admin_user: User,
        db_session: AsyncSession,
    ) -> None:
        other = await make_user(db_session)
        foreign = await _task(db_session, other.id)

        ids = {item["id"] for item in (await admin_client.get("/tasks")).json()}
        single = await admin_client.get(f"/tasks/{foreign.id}")

        assert str(foreign.id) in ids
        assert single.status_code == 200
        assert single.json()["created_by"] == str(other.id)

    @pytest.mark.parametrize(
        ("method", "suffix", "payload"),
        [
            ("get", "", None),
            ("patch", "", {"title": "чужое"}),
            ("get", "/node-logs", None),
            ("post", "/start", None),
            ("post", "/duplicate", {"code": "RR-DUP01", "title": "t", "description": "d"}),
            ("get", "/env-variables", None),
        ],
        ids=["get", "patch", "node_logs", "start", "duplicate", "env_variables"],
    )
    async def test_foreign_task_is_404(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
        method: str,
        suffix: str,
        payload: dict[str, Any] | None,
    ) -> None:
        other = await make_user(db_session)
        foreign = await _task(db_session, other.id)

        response = await authed_client.request(
            method.upper(),
            f"/tasks/{foreign.id}{suffix}",
            json=payload,
        )

        assert response.status_code == 404

    async def test_awaiting_count_own_only(
        self,
        admin_client: AsyncClient,
        admin_user: User,
        db_session: AsyncSession,
    ) -> None:
        other = await make_user(db_session)
        before = (await admin_client.get("/tasks/awaiting-count")).json()["count"]
        await _task(db_session, other.id, status=TaskStatus.AWAITING_INPUT)
        await _task(db_session, admin_user.id, status=TaskStatus.PLAN_REVIEW)

        after = (await admin_client.get("/tasks/awaiting-count")).json()["count"]

        assert after == before + 1

    async def test_foreign_parent_is_404(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        other = await make_user(db_session)
        foreign = await _task(db_session, other.id)

        response = await authed_client.post(
            "/tasks",
            json={
                "code": f"RR-{uuid.uuid4().hex[:6]}",
                "title": "t",
                "description": "d",
                "parent_task_id": str(foreign.id),
            },
        )

        assert response.status_code == 404

    async def test_foreign_pipeline_cannot_be_bound(
        self,
        authed_client: AsyncClient,
        current_user: User,
        db_session: AsyncSession,
    ) -> None:
        other = await make_user(db_session)
        task = await _task(db_session, current_user.id)
        pipeline = await _pipeline_with_node(db_session, other.id)

        response = await authed_client.post(
            f"/tasks/{task.id}/pipeline",
            json={"pipeline_id": str(pipeline.id)},
        )

        assert response.status_code == 404

    @pytest.mark.parametrize(
        ("foreign", "archived", "expected"),
        [(False, False, 201), (True, False, 404), (False, True, 409)],
        ids=["own", "foreign", "archived"],
    )
    async def test_library_prompt_rules(
        self,
        authed_client: AsyncClient,
        current_user: User,
        db_session: AsyncSession,
        foreign: bool,
        archived: bool,
        expected: int,
    ) -> None:
        owner = await make_user(db_session) if foreign else current_user
        task = await _task(db_session, current_user.id)
        node = await _library_node(db_session, owner.id, is_archived=archived)

        response = await authed_client.post(
            f"/tasks/{task.id}/library-prompts",
            json={"node_id": str(node.id)},
        )

        assert response.status_code == expected

    async def test_preview_of_foreign_task_is_404(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        other = await make_user(db_session)
        foreign = await _task(db_session, other.id)

        response = await authed_client.post(
            "/templates/preview",
            json={"text": "{{task.code}}", "scope": "freeform", "task_id": str(foreign.id)},
        )

        assert response.status_code == 404


class TestPipelines:
    async def test_create_sets_author(
        self,
        authed_client: AsyncClient,
        current_user: User,
    ) -> None:
        response = await authed_client.post("/pipelines", json={"name": "мой"})

        assert response.status_code == 201
        assert response.json()["created_by"] == str(current_user.id)

    async def test_list_shows_only_own(
        self,
        authed_client: AsyncClient,
        current_user: User,
        db_session: AsyncSession,
    ) -> None:
        other = await make_user(db_session)
        own = await _pipeline_with_node(db_session, current_user.id)
        foreign = await _pipeline_with_node(db_session, other.id)

        ids = {item["id"] for item in (await authed_client.get("/pipelines")).json()}

        assert str(own.id) in ids
        assert str(foreign.id) not in ids

    @pytest.mark.parametrize(
        ("method", "suffix", "payload"),
        [
            ("get", "", None),
            ("get", "/nodes", None),
            ("patch", "", {"name": "чужой"}),
            ("delete", "", None),
            ("post", "/dependents", {"node_id": str(uuid.uuid4()), "enabled_node_ids": []}),
        ],
        ids=["get", "nodes", "patch", "delete", "dependents"],
    )
    async def test_foreign_pipeline_is_404(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
        method: str,
        suffix: str,
        payload: dict[str, Any] | None,
    ) -> None:
        other = await make_user(db_session)
        foreign = await _pipeline_with_node(db_session, other.id)

        response = await authed_client.request(
            method.upper(),
            f"/pipelines/{foreign.id}{suffix}",
            json=payload,
        )

        assert response.status_code == 404


class TestNodes:
    async def test_library_prompt_belongs_to_creator(
        self,
        authed_client: AsyncClient,
        current_user: User,
    ) -> None:
        response = await authed_client.post(
            "/nodes",
            json={
                "name": "промт",
                "description": "назначение",
                "node_type": "plain_prompt",
                "prompt_template": "x",
            },
        )

        assert response.status_code == 201
        assert response.json()["created_by"] == str(current_user.id)

    async def test_node_in_foreign_pipeline_is_404(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        other = await make_user(db_session)
        foreign = await _pipeline_with_node(db_session, other.id)

        response = await authed_client.post(
            "/nodes",
            json={
                "pipeline_id": str(foreign.id),
                "order_index": 1,
                "name": "шаг",
                "node_type": "plain_prompt",
                "prompt_template": "x",
            },
        )

        assert response.status_code == 404

    async def test_admin_node_owned_by_author(
        self,
        admin_client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        owner = await make_user(db_session)
        pipeline = await _pipeline_with_node(db_session, owner.id)

        response = await admin_client.post(
            "/nodes",
            json={
                "pipeline_id": str(pipeline.id),
                "order_index": 1,
                "name": "шаг",
                "node_type": "plain_prompt",
                "prompt_template": "x",
            },
        )

        assert response.status_code == 201
        assert response.json()["created_by"] == str(owner.id)

    async def test_list_shows_only_own(
        self,
        authed_client: AsyncClient,
        current_user: User,
        db_session: AsyncSession,
    ) -> None:
        other = await make_user(db_session)
        own = await _library_node(db_session, current_user.id)
        foreign = await _library_node(db_session, other.id)

        response = await authed_client.get("/nodes", params={"library_only": True})
        ids = {item["id"] for item in response.json()}

        assert str(own.id) in ids
        assert str(foreign.id) not in ids

    @pytest.mark.parametrize(
        ("method", "payload"),
        [("get", None), ("patch", {"is_archived": True}), ("delete", None)],
        ids=["get", "patch", "delete"],
    )
    async def test_foreign_node_is_404(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
        method: str,
        payload: dict[str, Any] | None,
    ) -> None:
        other = await make_user(db_session)
        foreign = await _library_node(db_session, other.id)

        response = await authed_client.request(
            method.upper(),
            f"/nodes/{foreign.id}",
            json=payload,
        )

        assert response.status_code == 404


class TestTemplates:
    async def test_create_sets_author(
        self,
        authed_client: AsyncClient,
        current_user: User,
    ) -> None:
        response = await authed_client.post(
            "/templates",
            json={"name": "мой", "files": {}, "mcp_server_ids": []},
        )

        assert response.status_code == 201
        assert response.json()["created_by"] == str(current_user.id)

    async def test_list_shows_only_own(
        self,
        authed_client: AsyncClient,
        current_user: User,
        db_session: AsyncSession,
    ) -> None:
        other = await make_user(db_session)
        own = await _template(db_session, current_user.id)
        foreign = await _template(db_session, other.id)

        ids = {item["id"] for item in (await authed_client.get("/templates")).json()}

        assert str(own.id) in ids
        assert str(foreign.id) not in ids

    @pytest.mark.parametrize(
        ("method", "payload"),
        [("get", None), ("patch", {"name": "чужой"}), ("delete", None)],
        ids=["get", "patch", "delete"],
    )
    async def test_foreign_template_is_404(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
        method: str,
        payload: dict[str, Any] | None,
    ) -> None:
        other = await make_user(db_session)
        foreign = await _template(db_session, other.id)

        response = await authed_client.request(
            method.upper(),
            f"/templates/{foreign.id}",
            json=payload,
        )

        assert response.status_code == 404


class TestRepositoryDefaultTemplate:
    """Решение №16: репозитории общие, шаблон по умолчанию `user` берёт только свой."""

    async def _create(
        self,
        client: AsyncClient,
        template_id: uuid.UUID | None,
    ) -> Any:
        return await client.post(
            "/repositories",
            json={
                "name": f"repo-{uuid.uuid4().hex[:6]}",
                "git_url": "git@gitlab.example.com:team/repo.git",
                "deploy_key": "ключ",
                "default_template_id": str(template_id) if template_id else None,
            },
        )

    @pytest.mark.parametrize(("foreign", "expected"), [(False, 201), (True, 404)])
    async def test_create(
        self,
        authed_client: AsyncClient,
        current_user: User,
        db_session: AsyncSession,
        foreign: bool,
        expected: int,
    ) -> None:
        owner = await make_user(db_session) if foreign else current_user
        template = await _template(db_session, owner.id)

        response = await self._create(authed_client, template.id)

        assert response.status_code == expected

    async def test_update_to_foreign_template_is_404(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        other = await make_user(db_session)
        foreign = await _template(db_session, other.id)
        created = await self._create(authed_client, None)

        response = await authed_client.patch(
            f"/repositories/{created.json()['id']}",
            json={"default_template_id": str(foreign.id)},
        )

        assert response.status_code == 404

    async def test_unchanged_foreign_template_passes(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        other = await make_user(db_session)
        foreign = await _template(db_session, other.id)
        repository = Repository(
            name=f"repo-{uuid.uuid4().hex[:6]}",
            git_url="git@gitlab.example.com:team/repo.git",
            default_template_id=foreign.id,
            deploy_key_encrypted=encrypt("ключ"),
        )
        db_session.add(repository)
        await db_session.flush()

        response = await authed_client.patch(
            f"/repositories/{repository.id}",
            json={"name": "новое имя", "default_template_id": str(foreign.id)},
        )

        assert response.status_code == 200
        assert response.json()["default_template_id"] == str(foreign.id)

    async def test_null_clears_template(
        self,
        authed_client: AsyncClient,
        current_user: User,
        db_session: AsyncSession,
    ) -> None:
        template = await _template(db_session, current_user.id)
        created = await self._create(authed_client, template.id)

        response = await authed_client.patch(
            f"/repositories/{created.json()['id']}",
            json={"default_template_id": None},
        )

        assert response.status_code == 200
        assert response.json()["default_template_id"] is None
