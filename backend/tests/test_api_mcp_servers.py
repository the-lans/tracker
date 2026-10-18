"""`api/mcp_servers.py` — правило 3 CLAUDE.md/раздел 3.2, 10.2, 10.5 ТЗ."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from db.models.enums import McpAuthType, McpIsolationMode

if TYPE_CHECKING:
    from httpx import AsyncClient


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


async def test_non_admin_cannot_list_mcp_servers(authed_client: AsyncClient) -> None:
    response = await authed_client.get("/mcp-servers")

    assert response.status_code == 403
