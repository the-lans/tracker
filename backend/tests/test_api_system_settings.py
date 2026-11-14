"""«Системные настройки» и их применение к новым нодам (раздел 15.5 ТЗ)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from db.models.enums import NodeType, ScriptLanguage
from services.system_settings import get_jira_url

if TYPE_CHECKING:
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession

_SETTINGS = {
    "default_timeout_seconds": 900,
    "default_max_retries": 2,
    "default_retry_base_delay_seconds": 10,
    "night_window_start": "02:30:00",
    "night_window_end": "06:45:00",
    "app_logs_retention_days": 60,
    "day_start_time": "09:30:00",
}


class TestSystemSettings:
    async def test_defaults_then_update(self, admin_client: AsyncClient) -> None:
        initial = await admin_client.get("/system-settings")
        assert initial.status_code == 200
        assert initial.json()["default_timeout_seconds"] == 600
        assert initial.json()["app_logs_retention_days"] == 30
        assert initial.json()["day_start_time"] == "08:00:00"
        assert "default_runner_image_python" not in initial.json()
        assert "default_runner_image_bash" not in initial.json()

        updated = await admin_client.put("/system-settings", json=_SETTINGS)

        assert updated.status_code == 200
        assert (await admin_client.get("/system-settings")).json() == _SETTINGS

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("default_timeout_seconds", 0),
            ("default_max_retries", 11),
            ("default_retry_base_delay_seconds", -1),
            ("app_logs_retention_days", -1),
            ("app_logs_retention_days", 3651),
            ("app_logs_retention_days", None),
            ("day_start_time", None),
            ("day_start_time", "25:00"),
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

    async def test_app_logs_forever(self, admin_client: AsyncClient) -> None:
        response = await admin_client.put(
            "/system-settings",
            json={**_SETTINGS, "app_logs_retention_days": 0},
        )

        assert response.json()["app_logs_retention_days"] == 0

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
    async def test_only_jira(self, admin_client: AsyncClient) -> None:
        """Доступ к GitLab API — в учётных данных Git: прежние поля не принимаются и не отдаются."""
        response = await admin_client.put(
            "/system-settings/integrations",
            json={"gitlab_url": "https://gitlab.example.com", "gitlab_token": "glpat-example"},
        )

        assert response.json() == {"jira_url": None}
        assert (await admin_client.get("/system-settings/integrations")).json() == {
            "jira_url": None,
        }

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
