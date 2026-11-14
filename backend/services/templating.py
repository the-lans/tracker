"""Шаблонизатор переменных `{{namespace.field}}` (раздел 4, 5, 5.1 ТЗ).

Два непересекающихся слоя:

- ``validate_template_variables`` — вызывается при СОХРАНЕНИИ пайплайна/
  промта/свободного поля; проверяет, что каждая использованная переменная в
  принципе доступна в данном контексте (раздел 5.1: недоступная переменная —
  ошибка валидации сохранения, а не рантайм-сбой).
- ``render_template`` — вызывается непосредственно перед отправкой в SDK
  или запуском контейнера (5.1); принимает уже готовый плоский словарь
  ``"namespace.field" -> значение`` и просто подставляет значения — сам не
  обращается к БД (правило C, "Архитектурные решения" плана реализации:
  сервисы получают данные через DI, не открывают сессию сами).
  ``render_arguments`` использует тот же рендер для каждого аргумента,
  сохраняя границы значений; контекст также передаётся вызывающим кодом.

Имя слэш-команды передаётся буквально. У настроенной нативной команды
``render_slash_arguments`` обрабатывает только аргументы. Ручной ввод
слэш-команд в чате остаётся буквальным.
"""

from __future__ import annotations

import re
import shlex
from collections.abc import Mapping, Sequence
from enum import StrEnum

from db.models.enums import NodeType
from services.command_arguments import CommandArguments, parse_arguments
from services.errors import ValidationError

VARIABLE_PATTERN = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\.([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")

# Раздел 3.1 (таблица tasks) + repos_path и artifacts_path — вычисляемые
# поля (раздел 5), не колонки таблицы.
TASK_FIELDS = frozenset(
    {
        "id",
        "code",
        "title",
        "description",
        "guide_url",
        "jira_issue_url",
        "status",
        "pipeline_id",
        "llm_account_id",
        "parent_task_id",
        "use_parent_summary",
        "session_id",
        "current_permission_mode",
        "auto_accept_plan",
        "remote_control_status",
        "scheduled_start_at",
        "auto_start_enabled",
        "created_at",
        "repos_path",
        "artifacts_path",
    },
)

# {{session.*}} — единственная переменная раздела 5.
SESSION_FIELDS = frozenset({"id"})

# {{node.*}} — раздел 5, с указанием, какой тип предшествующей ноды
# обязан существовать в пайплайне, чтобы переменная была доступна.
_SCRIPT_OUTPUT = "script_output"
_LLM_OUTPUT = "llm_output"
_LLM_OUTPUT_LAST_N = "llm_output_last_n"
_USER_INPUT = "user_input"
_PLAN_TEXT = "plan_text"

NODE_FIELD_REQUIRED_PRECEDING_TYPES: dict[str, frozenset[NodeType]] = {
    _SCRIPT_OUTPUT: frozenset({NodeType.SCRIPT}),
    _LLM_OUTPUT: frozenset({NodeType.PLAIN_PROMPT, NodeType.SLASH_COMMAND}),
    _LLM_OUTPUT_LAST_N: frozenset(NodeType),
    _USER_INPUT: frozenset({NodeType.PLAIN_PROMPT, NodeType.SLASH_COMMAND, NodeType.PLAN_PROMPT}),
    _PLAN_TEXT: frozenset({NodeType.PLAN_PROMPT}),
}

# {{node.guide_url}} — поле САМОЙ ноды (раздел 5): позиция в пайплайне не
# нужна, поэтому переменная доступна и промту библиотеки, но не свободному
# вводу — у него нет своей ноды.
NODE_NAMESPACE = "node"
NODE_GUIDE_URL = "guide_url"
NODE_GUIDE_URL_VARIABLE = f"{NODE_NAMESPACE}.{NODE_GUIDE_URL}"
NODE_SELF_FIELDS = frozenset({NODE_GUIDE_URL})


class RenderScope(StrEnum):
    """Три места ввода параметризованного текста (раздел 5.1)."""

    PIPELINE = "pipeline"
    LIBRARY = "library"
    FREEFORM = "freeform"


def validate_template_variables(
    template: str,
    *,
    scope: RenderScope,
    preceding_node_types: Sequence[NodeType] = (),
    current_node_llm_output_last_n: int | None = None,
) -> None:
    """Проверяет доступность всех переменных шаблона в данном контексте.

    ``preceding_node_types`` — типы нод пайплайна, идущих СТРОГО раньше
    ноды/точки, для которой валидируется шаблон, в порядке ``order_index``
    (для ``scope != PIPELINE`` не используется — там ``{{node.*}}`` целиком
    запрещён). ``current_node_llm_output_last_n`` — значение поля ноды,
    параметризующего ``{{node.llm_output_last_n}}`` (см. ``db/models/pipelines.py``).
    """
    for namespace, field in VARIABLE_PATTERN.findall(template):
        if namespace == "task":
            if field not in TASK_FIELDS:
                raise ValidationError(f"Неизвестная переменная {{{{task.{field}}}}}")
        elif namespace == "session":
            if field not in SESSION_FIELDS:
                raise ValidationError(f"Неизвестная переменная {{{{session.{field}}}}}")
        elif namespace == "env":
            continue  # имя переменной окружения — произвольное, раздел 5
        elif namespace == NODE_NAMESPACE:
            _validate_node_variable(
                field,
                scope=scope,
                preceding_node_types=preceding_node_types,
                current_node_llm_output_last_n=current_node_llm_output_last_n,
            )
        else:
            raise ValidationError(f"Неизвестное пространство имён переменной: {namespace}")


def _validate_node_variable(
    field: str,
    *,
    scope: RenderScope,
    preceding_node_types: Sequence[NodeType],
    current_node_llm_output_last_n: int | None,
) -> None:
    if field in NODE_SELF_FIELDS:
        if scope is RenderScope.FREEFORM:
            raise ValidationError(
                f"{{{{node.{field}}}}} недоступна в свободном поле ввода: у текста нет своей ноды",
            )
        return
    if scope is not RenderScope.PIPELINE:
        raise ValidationError(
            "{{node.*}} недоступны в библиотеке промтов и свободном поле ввода "
            "(нет фиксированной позиции «предыдущей ноды»)",
        )
    required_types = NODE_FIELD_REQUIRED_PRECEDING_TYPES.get(field)
    if required_types is None:
        raise ValidationError(f"Неизвестная переменная {{{{node.{field}}}}}")
    if not required_types.intersection(preceding_node_types):
        raise ValidationError(
            f"Переменная {{{{node.{field}}}}} недоступна: в пайплайне до этой "
            "ноды нет ноды подходящего типа",
        )
    if field == _LLM_OUTPUT_LAST_N and current_node_llm_output_last_n is None:
        raise ValidationError(
            "{{node.llm_output_last_n}} использована, но для ноды не задан "
            "параметр N (nodes.llm_output_last_n)",
        )


_SLASH_COMMAND_PREFIX = "/"


def is_slash_command_text(text: str) -> bool:
    """
    Раздел 4, 22: определяет ручной ввод слэш-команды в чате, который
    передаётся буквально, в отличие от настроенных аргументов ноды.
    """
    return text.lstrip().startswith(_SLASH_COMMAND_PREFIX)


def render_template(template: str, context: Mapping[str, str]) -> str:
    """Подставляет значения переменных; вызывается непосредственно перед отправкой в SDK.

    Отсутствие ключа в ``context`` для переменной, прошедшей
    ``validate_template_variables`` на этапе сохранения, — ошибка
    реализации вызывающего кода (контекст собран неполно), а не
    пользовательский сценарий, поэтому здесь поднимается `ValidationError`.
    """

    def _substitute(match: re.Match[str]) -> str:
        key = f"{match.group(1)}.{match.group(2)}"
        if key not in context:
            raise ValidationError(f"Нет значения для переменной {{{{{key}}}}} при рендеринге")
        return context[key]

    return VARIABLE_PATTERN.sub(_substitute, template)


def render_arguments(raw: str, *, name: str = "", context: Mapping[str, str]) -> CommandArguments:
    """
    Общий рендер аргументов с сохранением их границ. Контекст и доступные
    переменные определяет вызывающий код; значения не интерпретируются повторно.
    """
    if not VARIABLE_PATTERN.search(raw):
        return parse_arguments(raw, name=name)
    # Убираем пробелы внутри {{ ... }}, чтобы shlex не разбил одну переменную.
    normalized = VARIABLE_PATTERN.sub(lambda m: "{{" + m[1] + "." + m[2] + "}}", raw)
    arguments = parse_arguments(normalized, name=name)
    values = [render_template(value, context) for value in arguments.values]
    return CommandArguments(name=arguments.name, raw=shlex.join(values), values=values)


def validate_task_arguments(raw: str) -> None:
    """
    В конфигурации аргументов доступны только поля текущей задачи.
    """
    for namespace, field in VARIABLE_PATTERN.findall(raw):
        if namespace != "task" or field not in TASK_FIELDS:
            raise ValidationError(
                "В аргументах доступны только поля задачи {{task.*}}: "
                + "{{"
                + namespace
                + "."
                + field
                + "}}"
            )


def slash_command_arguments(invocation: str) -> str:
    parts = invocation.split(maxsplit=1)
    return parts[1] if len(parts) == 2 else ""


def render_slash_arguments(invocation: str, *, context: Mapping[str, str]) -> str:
    """
    Имя команды буквально; только настроенные аргументы подставляются один раз.
    """
    raw = slash_command_arguments(invocation)
    if not VARIABLE_PATTERN.search(raw):
        return invocation
    validate_task_arguments(raw)
    arguments = render_arguments(raw, context=context)
    return invocation.split(maxsplit=1)[0] + " " + arguments.raw
