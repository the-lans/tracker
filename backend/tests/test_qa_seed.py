"""
Создание репозитория QA-стенда с общим SSH-доступом и повторное наполнение.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import asyncssh
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.repositories import GitCredential, Repository
from services.crypto import decrypt, encrypt
from services.git_credentials import GitlabApiAccess, gitlab_api_access

_SEED_SCRIPT = Path(__file__).resolve().parents[2] / "scripts/qa/seed_qa_data.py"


@pytest.fixture
def qa_seed(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    spec = importlib.util.spec_from_file_location("qa_seed_test", _SEED_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # dataclass разрешает аннотации через зарегистрированный модуль.
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


class TestQARepository:
    @pytest.mark.parametrize("existing_access", [False, True])
    async def test_seed_is_idempotent(
        self,
        db_session: AsyncSession,
        qa_seed: ModuleType,
        existing_access: bool,
    ) -> None:
        key = asyncssh.generate_private_key("ssh-ed25519").export_private_key().decode()
        if existing_access:
            db_session.add(
                GitCredential(
                    name=qa_seed.GIT_CREDENTIAL_NAME,
                    kind="ssh_key",
                    host="qa-git",
                    username="git",
                    secret_encrypted=encrypt(key),
                )
            )
            await db_session.flush()
        await qa_seed._repository(db_session, key)
        await db_session.flush()
        await qa_seed._gitlab_api(db_session)
        repository = (await db_session.scalars(sa.select(Repository))).one()
        credential = (await db_session.scalars(sa.select(GitCredential))).one()
        assert repository.git_url == qa_seed.GIT_URL
        assert repository.git_credential_id == credential.id
        assert (credential.kind, credential.host) == ("ssh_key", "qa-git")
        assert decrypt(credential.secret_encrypted) == key
        assert gitlab_api_access(credential) == GitlabApiAccess(
            qa_seed.MOCKS_URL,
            qa_seed.GITLAB_TOKEN,
        )
        # Повторный запуск не заменяет ключ и не создаёт дубликаты.
        other_key = asyncssh.generate_private_key("ssh-ed25519").export_private_key().decode()
        credential.gitlab_api_token_encrypted = encrypt("admin-token")
        await qa_seed._repository(db_session, other_key)
        await db_session.flush()
        await qa_seed._gitlab_api(db_session)
        assert (await db_session.scalars(sa.select(Repository.id))).all() == [repository.id]
        assert (await db_session.scalars(sa.select(GitCredential.id))).all() == [credential.id]
        await db_session.refresh(credential)
        assert decrypt(credential.secret_encrypted) == key
        assert decrypt(credential.gitlab_api_token_encrypted or "") == "admin-token"
