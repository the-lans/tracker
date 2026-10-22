import uuid

import pytest

from db.models.enums import McpAuthType, McpIsolationMode, TaskStatus
from db.models.mcp import McpServer
from db.models.tasks import Task
from services.crypto import encrypt
from services.errors import ValidationError
from services.mcp_config import build_mcp_server_config, render_isolation_path


def _make_task(code: str) -> Task:
    return Task(
        id=uuid.uuid4(),
        code=code,
        title="t",
        description="d",
        created_by=uuid.uuid4(),
        status=TaskStatus.IN_PROGRESS,
    )


def _make_mcp_server(**overrides: object) -> McpServer:
    defaults: dict[str, object] = {
        "id": uuid.uuid4(),
        "name": "playwright",
        "url": "https://mcp.internal/playwright",
        "auth_type": McpAuthType.NONE,
        "auth_config_encrypted": encrypt(""),
        "is_healthy": True,
        "has_stateful_resource": False,
        "isolation_mode": None,
        "isolation_path_template": None,
    }
    defaults.update(overrides)
    return McpServer(**defaults)


def test_stateless_server_has_no_isolation_header() -> None:
    server = _make_mcp_server()
    task = _make_task("RR-00001")

    config = build_mcp_server_config(server, task=task)

    assert config["type"] == "http"
    assert config["url"] == server.url
    assert "X-Tracker-Isolation-Path" not in config["headers"]


def test_bearer_token_auth_sets_authorization_header() -> None:
    server = _make_mcp_server(
        auth_type=McpAuthType.BEARER_TOKEN,
        auth_config_encrypted=encrypt("secret-token"),
    )
    task = _make_task("RR-00001")

    config = build_mcp_server_config(server, task=task)

    assert config["headers"]["Authorization"] == "Bearer secret-token"


def test_api_key_auth_sets_api_key_header() -> None:
    server = _make_mcp_server(
        auth_type=McpAuthType.API_KEY,
        auth_config_encrypted=encrypt("my-key"),
    )
    task = _make_task("RR-00001")

    config = build_mcp_server_config(server, task=task)

    assert config["headers"]["X-Api-Key"] == "my-key"


def test_isolated_flag_sets_ephemeral_header() -> None:
    server = _make_mcp_server(
        has_stateful_resource=True,
        isolation_mode=McpIsolationMode.ISOLATED_FLAG,
    )
    task = _make_task("RR-00001")

    config = build_mcp_server_config(server, task=task)

    assert config["headers"]["X-Tracker-Isolation-Path"] == "ephemeral"


def test_per_task_data_dir_renders_task_specific_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRACKER_REPOS_ROOT", "/data/repos")
    server = _make_mcp_server(
        has_stateful_resource=True,
        isolation_mode=McpIsolationMode.PER_TASK_DATA_DIR,
        isolation_path_template="{{task.repos_path}}/.mcp-profiles/{{mcp_server.name}}",
    )
    task = _make_task("RR-00001")

    config = build_mcp_server_config(server, task=task)

    expected_path = "/data/repos/RR-00001/.mcp-profiles/playwright"
    assert config["headers"]["X-Tracker-Isolation-Path"] == expected_path


def test_per_task_data_dir_gives_different_tasks_different_paths() -> None:
    # Раздел 10.5: два параллельных таска обязаны получить РАЗНЫЕ пути —
    # иначе это и есть ошибка реализации "общесистемный путь без подстановки".
    server = _make_mcp_server(
        has_stateful_resource=True,
        isolation_mode=McpIsolationMode.PER_TASK_DATA_DIR,
        isolation_path_template="{{task.repos_path}}/.mcp-profiles/{{mcp_server.name}}",
    )
    task_a = _make_task("RR-00001")
    task_b = _make_task("RR-00002")

    config_a = build_mcp_server_config(server, task=task_a)
    config_b = build_mcp_server_config(server, task=task_b)

    path_a = config_a["headers"]["X-Tracker-Isolation-Path"]
    path_b = config_b["headers"]["X-Tracker-Isolation-Path"]
    assert path_a != path_b


def test_per_task_data_dir_without_template_raises_before_session_start() -> None:
    # Модель это уже не должна допускать (services/mcp_validation.py), но
    # build_mcp_server_config защищается ещё раз — раздел 10.5 требует
    # ловить это ДО старта сессии, а не тихо подставлять пустую строку.
    server = _make_mcp_server(
        has_stateful_resource=True,
        isolation_mode=McpIsolationMode.PER_TASK_DATA_DIR,
        isolation_path_template=None,
    )
    task = _make_task("RR-00001")

    with pytest.raises(ValidationError):
        build_mcp_server_config(server, task=task)


def test_render_isolation_path_substitutes_both_variables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TRACKER_REPOS_ROOT", "/data/repos")
    task = _make_task("RR-00042")
    server = _make_mcp_server(name="browser-tools")

    rendered = render_isolation_path(
        "{{task.repos_path}}/.mcp-profiles/{{mcp_server.name}}",
        task=task,
        mcp_server=server,
    )

    assert rendered == "/data/repos/RR-00042/.mcp-profiles/browser-tools"
