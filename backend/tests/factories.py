"""Фабрики тестовых записей, нужные во многих модулях тестов."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from db.models.enums import LlmAccountStatus, UserRole
from db.models.llm import LlmAccount
from db.models.users import User
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
