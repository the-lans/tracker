"""
Миграция `b9e1d4f7a2c6` (решение №19 плана): адрес и токен GitLab переезжают
из глобальных `env_variables` в `system_settings` и возвращаются при откате.

Проверяется на отдельной временной базе того же тестового Postgres, чтобы не
трогать схему, на которой идут остальные тесты.
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from services.crypto import decrypt, encrypt
from tests.migration_support import run_alembic

_PREVIOUS_REVISION = "a7c4e2f9b318"
_REVISION = "b9e1d4f7a2c6"


async def _seed_old_layout(engine: AsyncEngine) -> None:
    insert = sa.text(
        "INSERT INTO env_variables (id, key, value_encrypted, is_secret, scope) "
        "VALUES (:id, :key, :value, :is_secret, 'global')",
    )
    async with engine.begin() as connection:
        for key, value, is_secret in (
            ("GITLAB_URL", "https://gitlab.example.com", False),
            ("GITLAB_TOKEN", "glpat-example", True),
            ("API_URL", "https://api.example.com", False),
        ):
            await connection.execute(
                insert,
                {"id": uuid.uuid4(), "key": key, "value": encrypt(value), "is_secret": is_secret},
            )


class TestGitlabSettingsMigration:
    async def test_moves_values_and_back(self, scratch_database: str) -> None:
        run_alembic(scratch_database, "upgrade", _PREVIOUS_REVISION)
        engine = create_async_engine(scratch_database)
        try:
            await _seed_old_layout(engine)

            run_alembic(scratch_database, "upgrade", _REVISION)
            async with engine.connect() as connection:
                settings = (
                    await connection.execute(
                        sa.text("SELECT gitlab_url, gitlab_token_encrypted FROM system_settings"),
                    )
                ).one()
                keys_result = await connection.execute(sa.text("SELECT key FROM env_variables"))
                keys = set(keys_result.scalars())
            assert settings.gitlab_url == "https://gitlab.example.com"
            assert decrypt(settings.gitlab_token_encrypted) == "glpat-example"
            assert keys == {"API_URL"}

            run_alembic(scratch_database, "downgrade", _PREVIOUS_REVISION)
            async with engine.connect() as connection:
                rows = await connection.execute(
                    sa.text("SELECT key, value_encrypted FROM env_variables"),
                )
                restored = {key: decrypt(value) for key, value in rows}
        finally:
            await engine.dispose()
        assert restored == {
            "GITLAB_URL": "https://gitlab.example.com",
            "GITLAB_TOKEN": "glpat-example",
            "API_URL": "https://api.example.com",
        }
