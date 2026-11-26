"""Аутентификация через Google OAuth (раздел 19.1 ТЗ).

Верификация Google id_token вынесена за `GoogleIdTokenVerifier` (Protocol) —
тот же приём DI, что и `ClaudeAgentClientProtocol` (`clients/claude_agent.py`):
реальная реализация (`GoogleAuthLibraryVerifier`) обращается к Google по
сети, тесты подставляют фейк, реализующий тот же протокол.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

import sqlalchemy as sa
from google.auth.exceptions import GoogleAuthError, TransportError
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2 import id_token as google_id_token

from app_logging.config import get_logger
from db.models.enums import UserRole
from db.models.users import AllowedEmail, User
from db.queries.users import increment_session_version
from services.auth_tokens import SessionClaims
from services.errors import ExternalServiceError, ForbiddenError, UnauthorizedError

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger("auth")

# Раздел 19.1: причина отказа во входе — для человека, она показывается на странице входа.
UNVERIFIED_EMAIL_MESSAGE = "Email не подтверждён Google — вход запрещён"
BLOCKED_USER_MESSAGE = "Учётная запись заблокирована — обратитесь к администратору"
NOT_ALLOWED_MESSAGE = (
    "Вход для {email} не разрешён — попросите администратора добавить этот email в список допуска"
)
# Отказ по токену сессии (401): пользователь пропал, заблокирован или вышел везде.
INACTIVE_SESSION_MESSAGE = "Пользователь не найден или заблокирован"
REVOKED_SESSION_MESSAGE = "Сессия завершена — войдите заново"


@dataclass(frozen=True, slots=True)
class GoogleIdentity:
    email: str
    email_verified: bool


class GoogleIdTokenVerifier(Protocol):
    def verify(self, id_token_jwt: str) -> GoogleIdentity: ...


class GoogleAuthLibraryVerifier:
    """
    Реальная проверка подписи id_token через `google-auth` (раздел 19.1).
    """

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


async def verify_google_id_token(
    verifier: GoogleIdTokenVerifier,
    id_token_jwt: str,
) -> GoogleIdentity:
    """
    Раздел 19.1: недействительный или просроченный токен — 401, недоступность
    Google — 502. Проверка ходит в сеть синхронно, поэтому выполняется в
    отдельном потоке и не останавливает остальные запросы.
    """
    try:
        return await asyncio.to_thread(verifier.verify, id_token_jwt)
    except TransportError as exc:
        message = "Google недоступен — повторите вход позже"
        raise ExternalServiceError(message, is_transient=True) from exc
    except (GoogleAuthError, ValueError) as exc:
        logger.info("google_id_token_rejected", error=str(exc))
        raise UnauthorizedError("Вход через Google не подтверждён — войдите заново") from exc


async def authenticate_or_register(
    db_session: AsyncSession,
    *,
    identity: GoogleIdentity,
) -> User:
    """Вход разрешён только активным пользователям из списка допуска."""
    if not identity.email_verified:
        raise ForbiddenError(UNVERIFIED_EMAIL_MESSAGE)

    is_allowed = await db_session.scalar(
        sa.select(AllowedEmail.id).where(AllowedEmail.email == identity.email).limit(1),
    )
    if is_allowed is None:
        raise ForbiddenError(NOT_ALLOWED_MESSAGE.format(email=identity.email))

    existing_user = await db_session.scalar(sa.select(User).where(User.email == identity.email))
    if existing_user is not None:
        if not existing_user.is_active:
            raise ForbiddenError(BLOCKED_USER_MESSAGE)
        return existing_user

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


async def load_session_user(db_session: AsyncSession, claims: SessionClaims) -> User:
    """
    Раздел 19.1: пользователь токена — активный и с той же версией сессий;
    после «Выйти на всех устройствах» прежние токены отклоняются.
    """
    user = await db_session.get(User, claims.user_id)
    if user is None or not user.is_active:
        raise UnauthorizedError(INACTIVE_SESSION_MESSAGE)
    if user.session_version != claims.session_version:
        raise UnauthorizedError(REVOKED_SESSION_MESSAGE)
    return user


async def revoke_user_sessions(db_session: AsyncSession, user: User) -> None:
    """
    Раздел 19.1: «Выйти на всех устройствах» — все выданные токены недействительны.
    """
    await increment_session_version(db_session, user.id)
    await db_session.commit()
    logger.info("user_sessions_revoked", user_id=str(user.id))
