import pytest

from db.models.enums import NodeType
from services.errors import ValidationError
from services.templating import (
    RenderScope,
    is_slash_command_text,
    render_template,
    validate_template_variables,
)


def test_render_template_substitutes_values() -> None:
    result = render_template(
        "Задача {{task.code}}: {{task.title}}",
        {"task.code": "RR-00001", "task.title": "починить баг"},
    )
    assert result == "Задача RR-00001: починить баг"


def test_render_template_missing_key_raises() -> None:
    with pytest.raises(ValidationError):
        render_template("{{task.code}}", {})


def test_render_template_is_noop_on_text_without_variables() -> None:
    # Слэш-команды (command_invocation) никогда не проходят через
    # шаблонизатор (раздел 4) — диспетчеризация по node_type это
    # обеспечивает (раздел 11.3, реализуется в Этапе 6). Этот тест лишь
    # показывает, что сам рендер безвреден на тексте без `{{...}}`.
    command = "/review $ARGUMENTS"
    assert render_template(command, {}) == command


@pytest.mark.parametrize("field", ["code", "title", "repos_path", "guide_url"])
def test_validate_known_task_fields_pass(field: str) -> None:
    validate_template_variables(f"{{{{task.{field}}}}}", scope=RenderScope.PIPELINE)


def test_validate_unknown_task_field_raises() -> None:
    with pytest.raises(ValidationError):
        validate_template_variables("{{task.nonexistent}}", scope=RenderScope.PIPELINE)


def test_validate_unknown_session_field_raises() -> None:
    with pytest.raises(ValidationError):
        validate_template_variables("{{session.token}}", scope=RenderScope.PIPELINE)


def test_validate_session_id_passes() -> None:
    validate_template_variables("{{session.id}}", scope=RenderScope.PIPELINE)


def test_validate_env_allows_any_key() -> None:
    validate_template_variables("{{env.ANY_CUSTOM_KEY}}", scope=RenderScope.PIPELINE)


def test_validate_unknown_namespace_raises() -> None:
    with pytest.raises(ValidationError):
        validate_template_variables("{{bogus.field}}", scope=RenderScope.PIPELINE)


@pytest.mark.parametrize("scope", [RenderScope.LIBRARY, RenderScope.FREEFORM])
def test_validate_node_variables_forbidden_outside_pipeline(scope: RenderScope) -> None:
    with pytest.raises(ValidationError):
        validate_template_variables("{{node.llm_output}}", scope=scope)


@pytest.mark.parametrize(
    ("field", "producing_type"),
    [
        ("script_output", NodeType.SCRIPT),
        ("llm_output", NodeType.PLAIN_PROMPT),
        ("llm_output", NodeType.SLASH_COMMAND),
        ("user_input", NodeType.PLAN_PROMPT),
        ("plan_text", NodeType.PLAN_PROMPT),
    ],
)
def test_validate_node_variable_passes_with_matching_preceding_node(
    field: str,
    producing_type: NodeType,
) -> None:
    validate_template_variables(
        f"{{{{node.{field}}}}}",
        scope=RenderScope.PIPELINE,
        preceding_node_types=[producing_type],
    )


def test_validate_node_variable_fails_without_matching_preceding_node() -> None:
    # {{node.script_output}} в первой ноде пайплайна — нет предыдущей
    # скрипт-ноды, поэтому это ошибка валидации сохранения (раздел 5.1).
    with pytest.raises(ValidationError):
        validate_template_variables(
            "{{node.script_output}}",
            scope=RenderScope.PIPELINE,
            preceding_node_types=[],
        )


def test_validate_node_variable_fails_with_wrong_preceding_type() -> None:
    with pytest.raises(ValidationError):
        validate_template_variables(
            "{{node.plan_text}}",
            scope=RenderScope.PIPELINE,
            preceding_node_types=[NodeType.PLAIN_PROMPT],
        )


def test_validate_unknown_node_field_raises() -> None:
    with pytest.raises(ValidationError):
        validate_template_variables(
            "{{node.nonexistent}}",
            scope=RenderScope.PIPELINE,
            preceding_node_types=[NodeType.SCRIPT],
        )


def test_validate_llm_output_last_n_requires_configured_n_on_node() -> None:
    with pytest.raises(ValidationError):
        validate_template_variables(
            "{{node.llm_output_last_n}}",
            scope=RenderScope.PIPELINE,
            preceding_node_types=[NodeType.PLAIN_PROMPT],
            current_node_llm_output_last_n=None,
        )


def test_validate_llm_output_last_n_passes_when_configured() -> None:
    validate_template_variables(
        "{{node.llm_output_last_n}}",
        scope=RenderScope.PIPELINE,
        preceding_node_types=[NodeType.PLAIN_PROMPT],
        current_node_llm_output_last_n=5,
    )


class TestIsSlashCommandText:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [("/review", True), ("  /review now", True), ("сделай /review", False), ("", False)],
    )
    def test_detects_leading_slash(self, text: str, expected: bool) -> None:
        assert is_slash_command_text(text) is expected
