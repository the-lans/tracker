"""Валидация MCP-сервера при сохранении (раздел 3.2, 10.2, 10.5 ТЗ).

`has_stateful_resource = true` требует явного `isolation_mode`, отличного
от `none`/`NULL` — сохранение без этого запрещено на уровне API, не БД
(правило 3 CLAUDE.md).
"""

from __future__ import annotations

from db.models.enums import McpIsolationMode
from services.errors import ValidationError

# Раздел 3.1: `isolation_path_template`, например
# `{{task.repos_path}}/.mcp-profiles/{{mcp_server.name}}` — без этой
# переменной путь общесистемный для ВСЕХ задач, что и есть та самая ошибка
# реализации, которую раздел 10.5 требует ловить до старта сессии.
REQUIRED_ISOLATION_PATH_VARIABLE = "{{task.repos_path}}"


def validate_mcp_server_isolation(
    *,
    has_stateful_resource: bool,
    isolation_mode: McpIsolationMode | None,
    isolation_path_template: str | None = None,
) -> None:
    if not has_stateful_resource:
        return
    if isolation_mode is None or isolation_mode == McpIsolationMode.NONE:
        raise ValidationError(
            "MCP-сервер с состоянием (has_stateful_resource=true) обязан иметь "
            "isolation_mode, отличный от none",
        )
    if isolation_mode is McpIsolationMode.PER_TASK_DATA_DIR:
        validate_isolation_path_template(isolation_path_template)


def validate_isolation_path_template(isolation_path_template: str | None) -> None:
    """Раздел 10.5: путь обязан ссылаться на `{{task.repos_path}}`.

    Без этого профиль окажется общим для всех задач — именно ту ошибку
    реализации, которую раздел 10.5 требует отлавливать до старта сессии
    (там же: "обязана отлавливаться на этапе integration-тестирования"),
    здесь она ловится ещё раньше — на этапе сохранения конфигурации.
    """
    if isolation_path_template is None:
        raise ValidationError(
            "isolation_mode=per_task_data_dir требует заполненного isolation_path_template",
        )
    if REQUIRED_ISOLATION_PATH_VARIABLE not in isolation_path_template:
        raise ValidationError(
            f"isolation_path_template обязан ссылаться на {REQUIRED_ISOLATION_PATH_VARIABLE} — "
            "иначе профиль окажется общим для всех задач (раздел 10.5 ТЗ)",
        )
