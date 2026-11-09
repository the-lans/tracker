"""
Миграция `f2c7a9d4e815`: доступ к GitLab API переезжает из системных настроек
в учётные данные Git с тем же хостом. Проверяется на отдельной временной базе.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from services.crypto import decrypt, encrypt
from tests.migration_support import run_alembic

_PREVIOUS_REVISION = "e6b8c20d1749"
_REVISION = "f2c7a9d4e815"
_TOKEN = "glpat-example"
_CREDENTIAL_HOSTS = (("Основной", "GitLab.example.com"), ("Партнёр", "git.partner.example.com"))


async def _seed(engine: AsyncEngine, *, gitlab_url: str | None, token: str | None) -> None:
    async with engine.begin() as connection:
        await connection.execute(
            sa.text(
                "INSERT INTO system_settings (id, default_timeout_seconds, default_max_retries, "
                "default_retry_base_delay_seconds, default_runner_image_python, "
                "default_runner_image_bash, gitlab_url, gitlab_token_encrypted) "
                "VALUES (1, 600, 2, 30, 'py', 'sh', :url, :token) "
                "ON CONFLICT (id) DO UPDATE SET gitlab_url = :url, gitlab_token_encrypted = :token",
            ),
            {"url": gitlab_url, "token": encrypt(token) if token else None},
        )
        for name, host in _CREDENTIAL_HOSTS:
            await connection.execute(
                sa.text(
                    "INSERT INTO git_credentials "
                    "(id, name, kind, host, username, secret_encrypted) "
                    "VALUES (:id, :name, 'ssh_key', :host, 'oauth2', :secret)",
                ),
                {"id": uuid.uuid4(), "name": name, "host": host, "secret": encrypt("key")},
            )


async def _credentials(engine: AsyncEngine) -> dict[str, Any]:
    async with engine.connect() as connection:
        rows = await connection.execute(
            sa.text(
                "SELECT name, gitlab_api_enabled, gitlab_api_token_encrypted, gitlab_api_url "
                "FROM git_credentials",
            ),
        )
        return {
            row.name: (
                row.gitlab_api_enabled,
                decrypt(row.gitlab_api_token_encrypted) if row.gitlab_api_token_encrypted else None,
                row.gitlab_api_url,
            )
            for row in rows
        }


class TestGitlabApiCredentialsMigration:
    @pytest.mark.parametrize(
        ("gitlab_url", "token", "expected"),
        [
            pytest.param(
                "https://gitlab.example.com/",
                _TOKEN,
                {
                    "Основной": (True, _TOKEN, None),
                    "Партнёр": (False, None, None),
                },
                id="тот же хост, адрес по умолчанию",
            ),
            pytest.param(
                "https://gitlab.example.com:8443/gitlab",
                _TOKEN,
                {
                    "Основной": (True, _TOKEN, "https://gitlab.example.com:8443/gitlab"),
                    "Партнёр": (False, None, None),
                },
                id="свой порт и подкаталог",
            ),
            pytest.param(
                "https://gitlab.example.com",
                None,
                {"Основной": (False, None, None), "Партнёр": (False, None, None)},
                id="без токена",
            ),
            pytest.param(
                None,
                None,
                {"Основной": (False, None, None), "Партнёр": (False, None, None)},
                id="не настроено",
            ),
        ],
    )
    async def test_transfer(
        self,
        scratch_database: str,
        gitlab_url: str | None,
        token: str | None,
        expected: dict[str, Any],
    ) -> None:
        run_alembic(scratch_database, "upgrade", _PREVIOUS_REVISION)
        engine = create_async_engine(scratch_database)
        try:
            await _seed(engine, gitlab_url=gitlab_url, token=token)
            run_alembic(scratch_database, "upgrade", _REVISION)
            assert await _credentials(engine) == expected
        finally:
            await engine.dispose()

    async def test_downgrade_keeps_system_settings(self, scratch_database: str) -> None:
        run_alembic(scratch_database, "upgrade", _PREVIOUS_REVISION)
        engine = create_async_engine(scratch_database)
        try:
            await _seed(engine, gitlab_url="https://gitlab.example.com", token=_TOKEN)
            run_alembic(scratch_database, "upgrade", _REVISION)
            run_alembic(scratch_database, "downgrade", _PREVIOUS_REVISION)
            async with engine.connect() as connection:
                columns = set(
                    (
                        await connection.execute(
                            sa.text(
                                "SELECT column_name FROM information_schema.columns "
                                "WHERE table_name = 'git_credentials'",
                            ),
                        )
                    ).scalars(),
                )
                settings = (
                    await connection.execute(
                        sa.text("SELECT gitlab_url, gitlab_token_encrypted FROM system_settings"),
                    )
                ).one()
        finally:
            await engine.dispose()
        assert not {c for c in columns if c.startswith("gitlab_api")}
        assert settings.gitlab_url == "https://gitlab.example.com"
        assert decrypt(settings.gitlab_token_encrypted) == _TOKEN
