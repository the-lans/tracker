"""TWG: личные доступы, шифрование и изоляция сессий пользователей."""

from __future__ import annotations

import json
import uuid
from typing import TYPE_CHECKING

import pytest

import session_cli
from api.dependencies import get_current_user
from clients.claude_agent import build_claude_agent_options
from db.models.twg import TwgConnection
from main import app
from services import docker_mounts, twg
from services.crypto import decrypt
from services.session_container import build_session_cli_env
from tests.factories import make_user

if TYPE_CHECKING:
    from pathlib import Path

    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession

    from db.models.users import User


async def test_personal_connection_lifecycle(
    authed_client: AsyncClient,
    current_user: User,
    db_session: AsyncSession,
) -> None:
    assert (await authed_client.get("/profile/twg")).json()["configured"] is False
    body = {
        "site": "https://example.atlassian.net/",
        "email": "person@example.com",
        "token": "personal-test-token",
    }
    response = await authed_client.put("/profile/twg", json=body)
    assert response.status_code == 200
    assert response.json() == {
        "enabled": True,
        "configured": True,
        "site": "example.atlassian.net",
        "email": "person@example.com",
    }
    row = await db_session.get(TwgConnection, current_user.id)
    assert row is not None
    assert row.token_encrypted != body["token"]
    assert decrypt(row.token_encrypted) == body["token"]
    other = await make_user(db_session)
    assert await twg.session_environment(db_session, other.id) == {}
    assert (await twg.session_environment(db_session, current_user.id))["TWG_TOKEN"] == body[
        "token"
    ]
    app.dependency_overrides[get_current_user] = lambda: other
    try:
        assert (await authed_client.get("/profile/twg")).json()["configured"] is False
        await authed_client.delete("/profile/twg")
        assert await db_session.get(TwgConnection, current_user.id) is not None
    finally:
        app.dependency_overrides[get_current_user] = lambda: current_user
    saved = await authed_client.put("/profile/twg", json={**body, "token": None})
    assert saved.status_code == 200
    assert decrypt(row.token_encrypted) == body["token"]
    replacement = await authed_client.put("/profile/twg", json={**body, "token": "replacement"})
    assert replacement.status_code == 200
    assert decrypt(row.token_encrypted) == "replacement"
    assert (await authed_client.delete("/profile/twg")).json()["configured"] is False
    assert await twg.session_environment(db_session, current_user.id) == {}
    assert (await authed_client.delete("/profile/twg")).status_code == 200


@pytest.mark.parametrize(
    "site",
    [
        "localhost",
        "http://example.atlassian.net",
        "example.atlassian.net@evil.com",
        "example.atlassian.net/path",
        "example.atlassian.net:443",
        "example.atlassian.net?token=value",
        "https://[invalid",
        "example.\natlassian.net",
    ],
)
async def test_invalid_site_is_rejected(authed_client: AsyncClient, site: str) -> None:
    response = await authed_client.put(
        "/profile/twg",
        json={
            "site": site,
            "email": "person@example.com",
            "token": "test-token",
        },
    )
    assert response.status_code == 422


async def test_token_required_and_cannot_follow_changed_identity(
    authed_client: AsyncClient,
) -> None:
    body = {"site": "example.atlassian.net", "email": "person@example.com"}
    assert (await authed_client.put("/profile/twg", json=body)).status_code == 422
    for token in ["", "has whitespace", "test\nvalue"]:
        assert (
            await authed_client.put("/profile/twg", json={**body, "token": token})
        ).status_code == 422
    assert (
        await authed_client.put("/profile/twg", json={**body, "email": "bad", "token": "t"})
    ).status_code == 422
    await authed_client.put("/profile/twg", json={**body, "token": "saved-token"})
    for changed in [{"site": "other.atlassian.net"}, {"email": "other@example.com"}]:
        response = await authed_client.put("/profile/twg", json={**body, **changed})
        assert response.status_code == 422
        assert "saved-token" not in response.text


async def test_requires_authentication(api_client: AsyncClient) -> None:
    assert (await api_client.get("/profile/twg")).status_code == 401
    assert (await api_client.delete("/profile/twg")).status_code == 401


def test_worker_environment_cannot_supply_twg_credentials() -> None:
    env = {
        "TWG_TOKEN": "worker-secret",
        "TWG_USER": "worker@example.com",
        "TWG_AUTH_STORAGE_KEY": "worker-key",
        "TWG_ENDPOINT": "https://evil.example",
    }
    env[session_cli.DOCKER_SPEC_ENV] = json.dumps(
        {
            "name_prefix": "test-",
            "docker_args": [],
            "image": "session",
        }
    )
    args = session_cli.build_command([], env)
    assert not any(name in args for name in env if name.startswith("TWG_"))
    spec = json.loads(env[session_cli.DOCKER_SPEC_ENV])
    spec["twg_authenticated"] = True
    env[session_cli.DOCKER_SPEC_ENV] = json.dumps(spec)
    args = session_cli.build_command([], env)
    assert "TWG_TOKEN" in args and "TWG_USER" in args
    assert "worker-secret" not in args
    assert "TWG_AUTH_STORAGE_KEY" not in args and "TWG_ENDPOINT" not in args


async def test_disabled_twg_does_not_forward_credentials(
    authed_client: AsyncClient,
    current_user: User,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await authed_client.put(
        "/profile/twg",
        json={
            "site": "example.atlassian.net",
            "email": "person@example.com",
            "token": "saved-token",
        },
    )
    monkeypatch.setenv("TRACKER_TWG_ENABLED", "false")
    assert await twg.session_environment(db_session, current_user.id) == {}
    assert (await authed_client.get("/profile/twg")).json()["enabled"] is False
    options = build_claude_agent_options(
        resume_session_id=None,
        cwd="/tmp",
        permission_mode=None,
        mcp_servers={},
        claude_config_dir="/tmp/session",
        enable_remote_control=False,
        cli_path="/app/session_cli.py",
    )
    assert options.plugins == []


def test_container_session_loads_shared_plugin() -> None:
    options = build_claude_agent_options(
        resume_session_id=None,
        cwd="/tmp",
        permission_mode=None,
        mcp_servers={},
        claude_config_dir="/tmp/session",
        enable_remote_control=False,
        cli_path="/app/session_cli.py",
    )
    assert options.plugins == [{"type": "local", "path": twg.TWG_PLUGIN_PATH}]
    assert "TWG" in str(options.system_prompt)


async def test_container_spec_does_not_contain_personal_token(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def host_directory(_root: Path) -> None:
        return None

    monkeypatch.setattr(docker_mounts, "resolve_root_mount", host_directory)
    monkeypatch.setenv("TRACKER_REPOS_ROOT", str(tmp_path / "repos"))
    monkeypatch.setenv("CLAUDE_SESSIONS_ROOT", str(tmp_path / "sessions"))
    personal = {
        "TWG_SITE": "example.atlassian.net",
        "TWG_USER": "person@example.com",
        "TWG_TOKEN": "session-personal-token",
    }
    env = await build_session_cli_env(
        task_id=uuid.uuid4(),
        cwd=tmp_path / "repos/RR-1",
        config_dir=tmp_path / "sessions/RR-1",
        session_token="gateway-token",
        twg_environment=personal,
    )
    assert env["TWG_TOKEN"] == personal["TWG_TOKEN"]
    assert personal["TWG_TOKEN"] not in env[session_cli.DOCKER_SPEC_ENV]
    command = session_cli.build_command([], env)
    assert "TWG_TOKEN" in command and personal["TWG_TOKEN"] not in command
