"""Тесты `services/system_settings.py` (раздел 15.5 ТЗ)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa

from db.models.enums import NodeType, ScriptLanguage
from db.models.pipelines import Node
from db.models.settings import SystemSettings
from services.system_settings import (
    DEFAULT_NODE_TIMEOUT_SECONDS,
    SystemSettingsValues,
    default_runner_image,
    get_system_settings,
    resolve_node_execution_defaults,
    resolve_runner_image,
    update_system_settings,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


_CUSTOM_SETTINGS = SystemSettingsValues(
    default_timeout_seconds=60,
    default_max_retries=1,
    default_retry_base_delay_seconds=0,
    default_runner_image_python="py:1",
    default_runner_image_bash="sh:1",
)


def _node(
    *,
    node_type: NodeType = NodeType.SCRIPT,
    language: ScriptLanguage | None = ScriptLanguage.BASH,
    docker_image: str | None = None,
) -> Node:
    return Node(
        name="n",
        node_type=node_type,
        script_language=language,
        docker_image=docker_image,
        timeout_seconds=1,
        is_library_item=True,
        is_archived=False,
    )


class TestSystemSettingsService:
    async def test_row_recreated_with_defaults(self, db_session: AsyncSession) -> None:
        await db_session.execute(sa.delete(SystemSettings))

        settings = await get_system_settings(db_session)

        assert settings.default_timeout_seconds == DEFAULT_NODE_TIMEOUT_SECONDS
        assert settings.default_runner_image_python == "tracker-runner-python:latest"

    @pytest.mark.parametrize(
        ("language", "expected"),
        [(ScriptLanguage.PYTHON, "py:1"), (ScriptLanguage.BASH, "sh:1")],
    )
    async def test_runner_image_by_language(
        self,
        db_session: AsyncSession,
        language: ScriptLanguage,
        expected: str,
    ) -> None:
        settings = await update_system_settings(db_session, values=_CUSTOM_SETTINGS)

        assert default_runner_image(settings, language) == expected


class TestNodeExecutionDefaults:
    async def test_empty_values_from_settings(self, db_session: AsyncSession) -> None:
        await update_system_settings(db_session, values=_CUSTOM_SETTINGS)

        defaults = await resolve_node_execution_defaults(
            db_session,
            timeout_seconds=None,
            max_retries=None,
            retry_base_delay_seconds=None,
        )

        assert (defaults.timeout_seconds, defaults.max_retries) == (60, 1)
        assert defaults.retry_base_delay_seconds == 0

    async def test_explicit_values_kept(self, db_session: AsyncSession) -> None:
        await update_system_settings(db_session, values=_CUSTOM_SETTINGS)

        defaults = await resolve_node_execution_defaults(
            db_session,
            timeout_seconds=30,
            max_retries=0,
            retry_base_delay_seconds=7,
        )

        assert (defaults.timeout_seconds, defaults.max_retries) == (30, 0)
        assert defaults.retry_base_delay_seconds == 7


class TestResolveRunnerImage:
    @pytest.mark.parametrize(
        ("node_kwargs", "expected"),
        [
            # Язык сменили после создания — образ берётся по текущему языку.
            ({"language": ScriptLanguage.BASH}, "sh:1"),
            ({"language": ScriptLanguage.PYTHON}, "py:1"),
            ({"docker_image": "custom:2"}, "custom:2"),
            ({"node_type": NodeType.PLAIN_PROMPT, "language": None}, None),
        ],
    )
    async def test_image(
        self,
        db_session: AsyncSession,
        node_kwargs: dict[str, object],
        expected: str | None,
    ) -> None:
        await update_system_settings(db_session, values=_CUSTOM_SETTINGS)

        assert await resolve_runner_image(db_session, _node(**node_kwargs)) == expected  # type: ignore[arg-type]
