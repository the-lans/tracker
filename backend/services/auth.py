"""Аутентификация через Google OAuth (раздел 19.1 ТЗ).

Верификация Google id_token вынесена за `GoogleIdTokenVerifier` (Protocol) —
тот же приём DI, что и `ClaudeAgentClientProtocol` (`clients/claude_agent.py`):
реальная реализация (`GoogleAuthLibraryVerifier`) обращается к Google по
сети, тесты подставляют фейк, реализующий тот же протокол.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

import sqlalchemy as sa
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2 import id_token as google_id_token

from app_logging.config import get_logger
from db.models.enums import UserRole
from db.models.users import AllowedEmail, User
from services.errors import ValidationError

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger("auth")


@dataclass(frozen=True, slots=True)
class GoogleIdentity:
    email: str
    email_verified: bool


class GoogleIdTokenVerifier(Protocol):
    def verify(self, id_token_jwt: str) -> GoogleIdentity: ...


class GoogleAuthLibraryVerifier:
    """Реальная проверка подписи id_token через `google-auth` (раздел 19.1)."""

    def __init__(self, *, client_id: str) -> None:
        self._client_id = client_id

    def verify(self, id_token_jwt: str) -> GoogleIdentity:
        # google-auth: verify_oauth2_token не аннотирован, несмотря на py.typed пакета.
        claims = google_id_token.verify_oauth2_token(  # type: ignore[no-untyped-call]
            id_token_jwt,
            GoogleAuthRequest(),
            audience=self._client_id,
        )
        return GoogleIdentity(
            email=str(claims["email"]),
            email_verified=bool(claims.get("email_verified", False)),
        )


async def authenticate_or_register(
    db_session: AsyncSession,
    *,
    identity: GoogleIdentity,
) -> User:
    """Раздел 19.1: вход/регистрация по email из подтверждённого Google id_token.

    Email обязан присутствовать в `allowed_emails` для НОВОГО пользователя —
    уже зарегистрированный пользователь входит независимо от того, остался
    ли его email в этом списке (администратор мог удалить email из списка
    уже после регистрации — это не отзывает существующий доступ автоматически,
    раздел 19.1 говорит только про условие РЕГИСТРАЦИИ).
    """
    if not identity.email_verified:
        raise ValidationError("Email не подтверждён Google — вход запрещён")

    existing_user = await db_session.scalar(sa.select(User).where(User.email == identity.email))
    if existing_user is not None:
        if not existing_user.is_active:
            raise ValidationError("Учётная запись заблокирована")
        return existing_user

    is_allowed = await db_session.scalar(
        sa.select(AllowedEmail.id).where(AllowedEmail.email == identity.email).limit(1),
    )
    if is_allowed is None:
        raise ValidationError(f"Email {identity.email} не в списке разрешённых (allowed_emails)")

    is_first_user = (await db_session.scalar(sa.select(User.id).limit(1))) is None
    user = User(
        id=uuid.uuid4(),
        email=identity.email,
        role=UserRole.ADMIN if is_first_user else UserRole.USER,
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    logger.info(
        "user_registered",
        email=identity.email,
        role=user.role,
        is_first_user=is_first_user,
    )
    return user
