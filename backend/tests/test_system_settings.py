"""Тесты `services/system_settings.py` (раздел 15.5 ТЗ)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa

from db.models.enums import ScriptLanguage
from db.models.settings import SystemSettings
from services.system_settings import (
    DEFAULT_NODE_TIMEOUT_SECONDS,
    SystemSettingsValues,
    default_runner_image,
    get_system_settings,
    update_system_settings,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


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
        settings = await update_system_settings(
            db_session,
            values=SystemSettingsValues(
                default_timeout_seconds=60,
                default_max_retries=1,
                default_retry_base_delay_seconds=0,
                default_runner_image_python="py:1",
                default_runner_image_bash="sh:1",
            ),
        )

        assert default_runner_image(settings, language) == expected
