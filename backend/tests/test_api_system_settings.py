"""«Системные настройки» и их применение к новым нодам (раздел 15.5 ТЗ)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from db.models.enums import NodeType, ScriptLanguage
from services.system_settings import get_gitlab_credentials, get_jira_url

if TYPE_CHECKING:
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession

_SETTINGS = {
    "default_timeout_seconds": 900,
    "default_max_retries": 2,
    "default_retry_base_delay_seconds": 10,
    "default_runner_image_python": "registry.local/runner-python:2",
    "default_runner_image_bash": "registry.local/runner-bash:2",
}


class TestSystemSettings:
    async def test_defaults_then_update(self, admin_client: AsyncClient) -> None:
        initial = await admin_client.get("/system-settings")
        assert initial.status_code == 200
        assert initial.json()["default_timeout_seconds"] == 600
        assert initial.json()["default_runner_image_bash"] == "tracker-runner-bash:latest"

        updated = await admin_client.put("/system-settings", json=_SETTINGS)

        assert updated.status_code == 200
        assert (await admin_client.get("/system-settings")).json() == _SETTINGS

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("default_timeout_seconds", 0),
            ("default_max_retries", 11),
            ("default_retry_base_delay_seconds", -1),
            ("default_runner_image_python", ""),
        ],
    )
    async def test_rejects_out_of_range(
        self,
        admin_client: AsyncClient,
        field: str,
        value: Any,
    ) -> None:
        response = await admin_client.put("/system-settings", json={**_SETTINGS, field: value})

        assert response.status_code == 422

    async def test_update_is_admin_only(self, authed_client: AsyncClient) -> None:
        assert (await authed_client.get("/system-settings")).status_code == 200
        response = await authed_client.put("/system-settings", json=_SETTINGS)

        assert response.status_code == 403


class TestNewNodeDefaults:
    async def test_taken_from_settings(self, admin_client: AsyncClient) -> None:
        await admin_client.put("/system-settings", json=_SETTINGS)

        response = await admin_client.post(
            "/nodes",
            json={
                "name": "Скрипт",
                "description": "d",
                "node_type": NodeType.SCRIPT.value,
                "script_language": ScriptLanguage.BASH.value,
                "script_content": "echo hi",
            },
        )

        assert response.status_code == 201, response.text
        body = response.json()
        assert body["timeout_seconds"] == 900
        assert body["max_retries"] == 2
        assert body["retry_base_delay_seconds"] == 10
        # Образ раннера выбирается при запуске, а не записывается в ноду.
        assert body["docker_image"] is None

    async def test_explicit_values_kept(self, admin_client: AsyncClient) -> None:
        await admin_client.put("/system-settings", json=_SETTINGS)

        response = await admin_client.post(
            "/nodes",
            json={
                "name": "Промт",
                "description": "d",
                "node_type": NodeType.PLAIN_PROMPT.value,
                "prompt_template": "x",
                "timeout_seconds": 30,
                "max_retries": 1,
            },
        )

        assert response.json()["timeout_seconds"] == 30
        assert response.json()["max_retries"] == 1
        assert response.json()["docker_image"] is None


class TestIntegrations:
    async def test_token_saved_but_never_returned(
        self,
        admin_client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        saved = await admin_client.put(
            "/system-settings/integrations",
            json={"gitlab_url": "https://gitlab.example.com", "gitlab_token": "glpat-example"},
        )

        assert saved.json() == {
            "gitlab_url": "https://gitlab.example.com",
            "gitlab_token_set": True,
            "jira_url": None,
        }
        assert "glpat-example" not in (await admin_client.get("/system-settings/integrations")).text
        credentials = await get_gitlab_credentials(db_session)
        assert credentials is not None
        assert credentials.token == "glpat-example"

    @pytest.mark.parametrize(
        ("token", "token_set"),
        [(None, True), ("", False)],
        ids=["keep", "clear"],
    )
    async def test_token_kept_or_cleared(
        self,
        admin_client: AsyncClient,
        token: str | None,
        token_set: bool,
    ) -> None:
        await admin_client.put(
            "/system-settings/integrations",
            json={"gitlab_url": "https://gitlab.example.com", "gitlab_token": "glpat-example"},
        )

        response = await admin_client.put(
            "/system-settings/integrations",
            json={"gitlab_url": "https://gitlab.example.com", "gitlab_token": token},
        )

        assert response.json()["gitlab_token_set"] is token_set

    async def test_jira_url_saved(
        self,
        admin_client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        response = await admin_client.put(
            "/system-settings/integrations",
            json={"jira_url": "https://jira.example.com/"},
        )

        assert response.json()["jira_url"] == "https://jira.example.com"
        assert await get_jira_url(db_session) == "https://jira.example.com"

    @pytest.mark.parametrize("method", ["get", "put"])
    async def test_admin_only(self, authed_client: AsyncClient, method: str) -> None:
        if method == "get":
            response = await authed_client.get("/system-settings/integrations")
        else:
            response = await authed_client.put("/system-settings/integrations", json={})
        assert response.status_code == 403
