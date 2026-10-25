import pytest

from db.models.enums import McpIsolationMode
from services.errors import ValidationError
from services.mcp_validation import (
    normalize_mcp_server_isolation,
    validate_isolation_path_template,
    validate_mcp_server_isolation,
)

_VALID_PER_TASK_TEMPLATE = "{{task.repos_path}}/.mcp-profiles/{{mcp_server.name}}"


def test_stateless_server_needs_no_isolation_mode() -> None:
    validate_mcp_server_isolation(has_stateful_resource=False, isolation_mode=None)


def test_stateful_server_with_isolated_flag_passes() -> None:
    validate_mcp_server_isolation(
        has_stateful_resource=True,
        isolation_mode=McpIsolationMode.ISOLATED_FLAG,
    )


def test_stateful_server_with_per_task_data_dir_and_valid_template_passes() -> None:
    validate_mcp_server_isolation(
        has_stateful_resource=True,
        isolation_mode=McpIsolationMode.PER_TASK_DATA_DIR,
        isolation_path_template=_VALID_PER_TASK_TEMPLATE,
    )


@pytest.mark.parametrize("isolation_mode", [None, McpIsolationMode.NONE])
def test_stateful_server_without_isolation_mode_is_rejected(
    isolation_mode: McpIsolationMode | None,
) -> None:
    with pytest.raises(ValidationError):
        validate_mcp_server_isolation(has_stateful_resource=True, isolation_mode=isolation_mode)


def test_per_task_data_dir_without_template_is_rejected() -> None:
    with pytest.raises(ValidationError):
        validate_mcp_server_isolation(
            has_stateful_resource=True,
            isolation_mode=McpIsolationMode.PER_TASK_DATA_DIR,
            isolation_path_template=None,
        )


def test_per_task_data_dir_with_systemwide_template_is_rejected() -> None:
    # Классическая ошибка реализации раздела 10.5: путь без {{task.repos_path}}
    # общий для всех задач.
    with pytest.raises(ValidationError):
        validate_mcp_server_isolation(
            has_stateful_resource=True,
            isolation_mode=McpIsolationMode.PER_TASK_DATA_DIR,
            isolation_path_template="/mnt/shared/mcp-profiles/playwright",
        )


def test_validate_isolation_path_template_accepts_task_repos_path() -> None:
    validate_isolation_path_template(_VALID_PER_TASK_TEMPLATE)


def test_validate_isolation_path_template_rejects_missing_variable() -> None:
    with pytest.raises(ValidationError):
        validate_isolation_path_template("/mnt/shared/mcp-profiles/playwright")


def test_validate_isolation_path_template_rejects_none() -> None:
    with pytest.raises(ValidationError):
        validate_isolation_path_template(None)


class TestNormalizeIsolation:
    """Раздел 3.1: лишние режим и шаблон пути не хранятся."""

    @pytest.mark.parametrize(
        ("stateful", "mode", "expected"),
        [
            (False, McpIsolationMode.PER_TASK_DATA_DIR, (None, None)),
            (True, McpIsolationMode.ISOLATED_FLAG, (McpIsolationMode.ISOLATED_FLAG, None)),
            (
                True,
                McpIsolationMode.PER_TASK_DATA_DIR,
                (McpIsolationMode.PER_TASK_DATA_DIR, _VALID_PER_TASK_TEMPLATE),
            ),
        ],
        ids=["stateless", "isolated_flag", "per_task_data_dir"],
    )
    def test_result(
        self,
        stateful: bool,
        mode: McpIsolationMode,
        expected: tuple[McpIsolationMode | None, str | None],
    ) -> None:
        assert (
            normalize_mcp_server_isolation(
                has_stateful_resource=stateful,
                isolation_mode=mode,
                isolation_path_template=_VALID_PER_TASK_TEMPLATE,
            )
            == expected
        )
