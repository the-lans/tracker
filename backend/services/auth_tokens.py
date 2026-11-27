"""Токен сессии API (раздел 19.1 ТЗ не называет механизм явно — HTTP/WS API
раздела 2.3/2.4/18.1 нужен какой-то способ подтверждать личность между
запросами после однократного обмена Google id_token; выбран
Fernet-подписанный непрозрачный токен, а не JWT, чтобы переиспользовать уже
принятый в проекте примитив (`services/crypto.py`) вместо добавления новой
библиотеки ради этой единственной задачи).

Ключ подписи — `SESSION_SECRET_KEY`, ОТДЕЛЬНЫЙ от `SECRET_ENCRYPTION_KEY`
(раздел 19.4: ключ шифрования секретов — вне БД, из окружения): смешивать
домен "подпись пользовательских сессий" с доменом "шифрование хранимых
секретов" в одном ключе значило бы, что компрометация одного домена сразу
компрометирует другой.

Токен несёт версию сессий пользователя (`users.session_version`): «Выйти на
всех устройствах» увеличивает её, и выданные раньше токены перестают
действовать. У токенов, выданных до появления версии, она считается 0.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from cryptography.fernet import Fernet, InvalidToken

from services.crypto import fernet_from_env

DEFAULT_SESSION_TTL = timedelta(days=7)


class InvalidSessionTokenError(Exception): ...


@dataclass(frozen=True, slots=True)
class SessionClaims:
    user_id: uuid.UUID
    session_version: int
    expires_at: datetime = field(
        default_factory=lambda: datetime.max.replace(tzinfo=UTC), compare=False
    )


_SESSION_KEY_ENV = "SESSION_SECRET_KEY"
_SESSION_VERSION_FIELD = "session_version"
# Версия новых пользователей и токенов, выданных до её появления.
INITIAL_SESSION_VERSION = 0


def _fernet() -> Fernet:
    return fernet_from_env(_SESSION_KEY_ENV)


def issue_session_token(
    user_id: uuid.UUID,
    *,
    session_version: int = INITIAL_SESSION_VERSION,
    ttl: timedelta = DEFAULT_SESSION_TTL,
) -> str:
    payload = {
        "user_id": str(user_id),
        "expires_at": (datetime.now(UTC) + ttl).isoformat(),
        _SESSION_VERSION_FIELD: session_version,
    }
    return _fernet().encrypt(json.dumps(payload).encode("utf-8")).decode("ascii")


def verify_session_token(token: str) -> SessionClaims:
    """
    Пользователь и версия сессий токена; поднимает `InvalidSessionTokenError`,
    если токен подделан или истёк. Совпадение версии с текущей проверяет
    `services/auth.py::load_session_user`.
    """
    try:
        raw = _fernet().decrypt(token.encode("ascii"))
    except (InvalidToken, UnicodeEncodeError) as exc:
        raise InvalidSessionTokenError("Токен сессии недействителен") from exc

    try:
        payload = json.loads(raw)
        expires_at = datetime.fromisoformat(payload["expires_at"])
        claims = SessionClaims(
            user_id=uuid.UUID(payload["user_id"]),
            session_version=int(payload.get(_SESSION_VERSION_FIELD, INITIAL_SESSION_VERSION)),
            expires_at=expires_at,
        )
        if expires_at.tzinfo is None:
            raise ValueError("Отсутствует часовой пояс")
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise InvalidSessionTokenError("Токен сессии недействителен") from exc
    if datetime.now(UTC) >= expires_at:
        raise InvalidSessionTokenError("Токен сессии истёк")
    return claims
