"""`api/mcp_servers.py` — правило 3 CLAUDE.md/раздел 3.2, 10.2, 10.5 ТЗ."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

import pytest

from db.models.enums import McpAuthType, McpIsolationMode
from db.models.mcp import McpServer
from services.crypto import encrypt

if TYPE_CHECKING:
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession


async def _create(client: AsyncClient, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": "postgres-mcp",
        "url": "http://localhost:8931",
        "auth_type": McpAuthType.NONE.value,
        "auth_config": "",
        "has_stateful_resource": False,
    }
    payload.update(overrides)
    response = await client.post("/mcp-servers", json=payload)
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


async def test_stateful_without_isolation_mode_is_rejected(admin_client: AsyncClient) -> None:
    response = await admin_client.post(
        "/mcp-servers",
        json={
            "name": "playwright",
            "url": "http://localhost:8932",
            "auth_type": McpAuthType.NONE.value,
            "auth_config": "",
            "has_stateful_resource": True,
        },
    )

    assert response.status_code == 422


async def test_per_task_isolation_requires_repos_path_variable(admin_client: AsyncClient) -> None:
    response = await admin_client.post(
        "/mcp-servers",
        json={
            "name": "playwright",
            "url": "http://localhost:8932",
            "auth_type": McpAuthType.NONE.value,
            "auth_config": "",
            "has_stateful_resource": True,
            "isolation_mode": McpIsolationMode.PER_TASK_DATA_DIR.value,
            "isolation_path_template": "/srv/shared/profile",
        },
    )

    assert response.status_code == 422


async def test_valid_stateful_mcp_server_is_created(admin_client: AsyncClient) -> None:
    body = await _create(
        admin_client,
        name="playwright",
        has_stateful_resource=True,
        isolation_mode=McpIsolationMode.PER_TASK_DATA_DIR.value,
        isolation_path_template="{{task.repos_path}}/.mcp-profiles/playwright",
    )

    assert body["has_stateful_resource"] is True
    assert "auth_config" not in body


async def test_update_to_stateful_without_isolation_mode_is_rejected(
    admin_client: AsyncClient,
) -> None:
    body = await _create(admin_client)

    response = await admin_client.patch(
        f"/mcp-servers/{body['id']}",
        json={"has_stateful_resource": True},
    )

    assert response.status_code == 422


class TestIsolationCleanup:
    """Раздел 3.1: при правке прежние режим и шаблон пути сбрасываются."""

    @pytest.mark.parametrize(
        ("patch", "expected"),
        [
            (
                {
                    "isolation_mode": McpIsolationMode.ISOLATED_FLAG.value,
                    "isolation_path_template": None,
                },
                (McpIsolationMode.ISOLATED_FLAG.value, None),
            ),
            (
                {
                    "has_stateful_resource": False,
                    "isolation_mode": None,
                    "isolation_path_template": None,
                },
                (None, None),
            ),
        ],
        ids=["isolated_flag", "stateless"],
    )
    async def test_stale_values_cleared(
        self,
        admin_client: AsyncClient,
        patch: dict[str, Any],
        expected: tuple[str | None, str | None],
    ) -> None:
        body = await _create(
            admin_client,
            name="playwright",
            has_stateful_resource=True,
            isolation_mode=McpIsolationMode.PER_TASK_DATA_DIR.value,
            isolation_path_template="{{task.repos_path}}/.mcp-profiles/playwright",
        )

        await admin_client.patch(f"/mcp-servers/{body['id']}", json=patch)
        stored = (await admin_client.get(f"/mcp-servers/{body['id']}")).json()

        assert (stored["isolation_mode"], stored["isolation_path_template"]) == expected


class TestUserAccess:
    """Раздел 10.5, 19.2: `user` выбирает серверы для своего шаблона, но не меняет их."""

    async def _server(self, db_session: AsyncSession) -> McpServer:
        server = McpServer(
            name=f"mcp-{uuid.uuid4().hex[:6]}",
            url="http://localhost:8931",
            auth_type=McpAuthType.BEARER_TOKEN,
            auth_config_encrypted=encrypt("secret-token"),
            is_healthy=True,
            has_stateful_resource=False,
        )
        db_session.add(server)
        await db_session.flush()
        return server

    async def test_reads_without_secrets(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        server = await self._server(db_session)

        listed = await authed_client.get("/mcp-servers")
        single = await authed_client.get(f"/mcp-servers/{server.id}")

        assert listed.status_code == 200
        assert str(server.id) in [item["id"] for item in listed.json()]
        assert single.status_code == 200
        assert "secret-token" not in listed.text + single.text
        assert "auth_config" not in single.json()

    @pytest.mark.parametrize(
        ("method", "with_id", "payload"),
        [
            ("post", False, {"name": "x", "url": "http://x", "auth_type": "none"}),
            ("patch", True, {"name": "y"}),
            ("delete", True, None),
        ],
        ids=["create", "update", "delete"],
    )
    async def test_cannot_modify(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
        method: str,
        with_id: bool,
        payload: dict[str, Any] | None,
    ) -> None:
        server = await self._server(db_session)
        url = f"/mcp-servers/{server.id}" if with_id else "/mcp-servers"

        response = await authed_client.request(method.upper(), url, json=payload)

        assert response.status_code == 403


class TestDeleteLinkedToTemplate:
    """Раздел 3.2: сервер шаблона не удаляется, шаблон удаляется вместе со связями."""

    async def test_server_then_template(self, admin_client: AsyncClient) -> None:
        server = await _create(admin_client)
        template = await admin_client.post(
            "/templates",
            json={"name": "шаблон", "files": {}, "mcp_server_ids": [server["id"]]},
        )
        assert template.status_code == 201, template.text

        server_response = await admin_client.delete(f"/mcp-servers/{server['id']}")
        assert server_response.status_code == 409
        assert "шаблон" in server_response.json()["error"]["message"]

        template_response = await admin_client.delete(f"/templates/{template.json()['id']}")
        assert template_response.status_code == 204
        assert (await admin_client.delete(f"/mcp-servers/{server['id']}")).status_code == 204
