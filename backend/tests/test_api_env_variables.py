"""`api/env_variables.py` — раздел 3.1, 5, 19.4 ТЗ; правило 8 CLAUDE.md
("значения скрыты в UI по умолчанию")."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from db.models.enums import EnvVariableScope

if TYPE_CHECKING:
    from httpx import AsyncClient


async def test_create_global_env_variable_hides_value_in_response(
    admin_client: AsyncClient,
) -> None:
    response = await admin_client.post(
        "/env-variables",
        json={
            "key": "GITLAB_API_TOKEN",
            "value": "glpat-secret",
            "scope": EnvVariableScope.GLOBAL.value,
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert "value" not in body
    assert body["key"] == "GITLAB_API_TOKEN"


async def test_reveal_returns_decrypted_value(admin_client: AsyncClient) -> None:
    created = (
        await admin_client.post(
            "/env-variables",
            json={
                "key": "SOME_SECRET",
                "value": "top-secret-value",
                "is_secret": True,
                "scope": EnvVariableScope.GLOBAL.value,
            },
        )
    ).json()

    response = await admin_client.get(f"/env-variables/{created['id']}/reveal")

    assert response.status_code == 200
    assert response.json()["value"] == "top-secret-value"


async def test_global_scope_rejects_repository_id(admin_client: AsyncClient) -> None:
    response = await admin_client.post(
        "/env-variables",
        json={
            "key": "X",
            "value": "y",
            "scope": EnvVariableScope.GLOBAL.value,
            "repository_id": str(uuid.uuid4()),
        },
    )

    assert response.status_code == 422


async def test_repository_scope_requires_repository_id(admin_client: AsyncClient) -> None:
    response = await admin_client.post(
        "/env-variables",
        json={"key": "X", "value": "y", "scope": EnvVariableScope.REPOSITORY.value},
    )

    assert response.status_code == 422


async def test_non_admin_cannot_create_env_variable(authed_client: AsyncClient) -> None:
    response = await authed_client.post(
        "/env-variables",
        json={"key": "X", "value": "y", "scope": EnvVariableScope.GLOBAL.value},
    )

    assert response.status_code == 403
