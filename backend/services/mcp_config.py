"""Сборка конфигурации MCP-серверов для сессии Claude Code (раздел 10, 10.5 ТЗ).

Раздел 3.1 хранит `mcp_servers.url` — сетевой адрес (SSE/HTTP transport), не
команду локального процесса, поэтому конфигурация всегда собирается как
`McpHttpServerConfig`. Изоляция ресурса с состоянием (раздел 10.2)
передаётся конкретному MCP-серверу через HTTP-заголовок
``X-Tracker-Isolation-Path`` — соответствие этому заголовку и фактическая
изоляция ресурса (браузерного профиля и т.п.) на стороне самого MCP-сервера
остаются ответственностью администратора, настраивающего конкретный сервер
(раздел 10.2: "выбор конкретного режима — ответственность администратора").

Раздел 10.5 прямо требует ловить ошибку реализации "путь без подстановки
задачи" на этапе integration-тестирования — рендеринг здесь выполняется
непосредственно перед стартом сессии (не заранее, раздел 5.1) и логируется
целиком, включая итоговый путь, до передачи в SDK.
"""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from claude_agent_sdk.types import McpHttpServerConfig

from app_logging.config import get_logger
from db.models.enums import McpAuthType, McpIsolationMode
from services.crypto import decrypt
from services.mcp_validation import validate_isolation_path_template
from services.template_context import REPOS_PATH_TEMPLATE
from services.templating import render_template

if TYPE_CHECKING:
    from db.models.mcp import McpServer
    from db.models.tasks import Task

logger = get_logger("mcp_config")

_ISOLATION_PATH_HEADER = "X-Tracker-Isolation-Path"
_ISOLATED_FLAG_HEADER_VALUE = "ephemeral"


def render_isolation_path(
    isolation_path_template: str,
    *,
    task: Task,
    mcp_server: McpServer,
) -> str:
    """Рендерит `isolation_path_template` (раздел 3.1) — свой, узкий набор
    переменных (`{{task.repos_path}}`, `{{mcp_server.name}}`), отдельный от
    общего раздела 5 (там нет `{{mcp_server.*}}`).

    ``PurePosixPath`` схлопывает двойной "/", получающийся из-за того, что
    ``task.repos_path`` (раздел 3.1) сам оканчивается на "/", а типовой
    пример шаблона в том же разделе добавляет ещё один разделитель после
    подстановки — безобидный, но не нужный артефакт рендеринга.
    """
    context = {
        "task.repos_path": REPOS_PATH_TEMPLATE.format(code=task.code),
        "mcp_server.name": mcp_server.name,
    }
    rendered = render_template(isolation_path_template, context)
    return str(PurePosixPath(rendered))


def _auth_headers(mcp_server: McpServer) -> dict[str, str]:
    if mcp_server.auth_type is McpAuthType.NONE:
        return {}
    token = decrypt(mcp_server.auth_config_encrypted)
    if mcp_server.auth_type is McpAuthType.BEARER_TOKEN:
        return {"Authorization": f"Bearer {token}"}
    return {"X-Api-Key": token}


def build_mcp_server_config(mcp_server: McpServer, *, task: Task) -> McpHttpServerConfig:
    """Собирает итоговую конфигурацию одного MCP-сервера для `ClaudeAgentOptions.mcp_servers`."""
    headers = _auth_headers(mcp_server)

    if mcp_server.has_stateful_resource:
        if mcp_server.isolation_mode is McpIsolationMode.ISOLATED_FLAG:
            headers[_ISOLATION_PATH_HEADER] = _ISOLATED_FLAG_HEADER_VALUE
        elif mcp_server.isolation_mode is McpIsolationMode.PER_TASK_DATA_DIR:
            template = mcp_server.isolation_path_template
            validate_isolation_path_template(template)
            assert template is not None  # validate_isolation_path_template уже это проверило
            rendered_path = render_isolation_path(template, task=task, mcp_server=mcp_server)
            logger.info(
                "mcp_isolation_path_rendered",
                mcp_server_id=str(mcp_server.id),
                task_code=task.code,
                rendered_path=rendered_path,
            )
            headers[_ISOLATION_PATH_HEADER] = rendered_path

    return McpHttpServerConfig(type="http", url=mcp_server.url, headers=headers)
