"""Фабрики тестовых записей, нужные во многих модулях тестов."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from db.models.enums import LlmAccountStatus, UserRole
from db.models.llm import LlmAccount
from db.models.pipelines import Pipeline
from db.models.repositories import Repository
from db.models.tasks import Task
from db.models.users import User
from services.crypto import encrypt
from services.llm_accounts import DEFAULT_ACCOUNTS_ROOT

# Сгенерированы `ssh-keygen` только для тестов; отпечатки — вывод `ssh-keygen -lf`.
SAMPLE_ED25519_BODY = "AAAAC3NzaC1lZDI1NTE5AAAAIMO38aJ53W0R6XWxn4RcBQx6yBRrPornlkBe44lO/nsV"
SAMPLE_ED25519_KEY = f"ssh-ed25519 {SAMPLE_ED25519_BODY} dev@example.com"
SAMPLE_ED25519_FINGERPRINT = "SHA256:EwXVWx/F4dl1Kgt0sJnDirzn8W0vYkpQYwjLMTu9qfc"
SAMPLE_ECDSA_KEY = (
    "ecdsa-sha2-nistp256 AAAAE2VjZHNhLXNoYTItbmlzdHAyNTYAAAAIbmlzdHAyNTYAAABBBI9f15X11zHCj7Zy"
    "54GcWq+hsFz5185M//eWoTlJ8OQS+SCf9Wg87PcfuzZkzHJmJeaxSNEhOD+X+o52VH2zJiY="
)
SAMPLE_ECDSA_FINGERPRINT = "SHA256:deDcy/dAfpt9w7Yl8dJvNU4do+VEZ5xDqxONY9lxNsc"


async def make_user(db_session: AsyncSession, *, role: UserRole = UserRole.USER) -> User:
    """Пользователь — автор пайплайнов, нод и шаблонов (раздел 19.2)."""
    user = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4()}@example.com",
        role=role,
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()
    return user


async def make_llm_account(
    db_session: AsyncSession,
    *,
    owner_id: uuid.UUID,
    claude_config_dir: str | None = None,
    status: LlmAccountStatus = LlmAccountStatus.ACTIVE,
) -> LlmAccount:
    """LLM-аккаунт пользователя (раздел 19.2): путь уникален, если не задан явно."""
    account = LlmAccount(
        label="main",
        claude_config_dir=claude_config_dir or f"{DEFAULT_ACCOUNTS_ROOT}/{uuid.uuid4().hex}",
        status=status,
        created_by=owner_id,
    )
    db_session.add(account)
    await db_session.flush()
    return account


def task_code() -> str:
    """Уникальный код задачи в формате примера ТЗ (`RR-…`)."""
    return f"RR-{uuid.uuid4().hex[:6]}"


async def make_task(
    db_session: AsyncSession,
    *,
    created_by: uuid.UUID | None = None,
    **fields: Any,
) -> Task:
    """
    Задача с минимальными полями; без ``created_by`` автор создаётся.
    Любое поле `tasks` переопределяется через ``fields``.
    """
    if created_by is None:
        created_by = (await make_user(db_session)).id
    values: dict[str, Any] = {"code": task_code(), "title": "t", "description": "d"}
    values.update(fields)
    task = Task(created_by=created_by, **values)
    db_session.add(task)
    await db_session.flush()
    return task


async def make_pipeline(db_session: AsyncSession, *, created_by: uuid.UUID) -> Pipeline:
    pipeline = Pipeline(name="p", is_archived=False, created_by=created_by)
    db_session.add(pipeline)
    await db_session.flush()
    return pipeline


def build_repository(
    *,
    name: str = "backend",
    git_url: str = "git@example.com:x.git",
    deploy_key: str = "k",
) -> Repository:
    """Репозиторий без записи в БД (для git-тестов без сессии)."""
    return Repository(
        id=uuid.uuid4(),
        name=name,
        git_url=git_url,
        deploy_key_encrypted=encrypt(deploy_key),
    )


async def make_repository(db_session: AsyncSession, **fields: Any) -> Repository:
    repository = build_repository(**fields)
    db_session.add(repository)
    await db_session.flush()
    return repository
