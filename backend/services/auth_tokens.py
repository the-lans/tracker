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
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import uuid
from datetime import UTC, datetime, timedelta
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

DEFAULT_SESSION_TTL = timedelta(days=7)


class InvalidSessionTokenError(Exception): ...


def _derive_fernet_key(secret: str) -> bytes:
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    secret = os.environ["SESSION_SECRET_KEY"]
    return Fernet(_derive_fernet_key(secret))


def issue_session_token(user_id: uuid.UUID, *, ttl: timedelta = DEFAULT_SESSION_TTL) -> str:
    payload = {
        "user_id": str(user_id),
        "expires_at": (datetime.now(UTC) + ttl).isoformat(),
    }
    return _fernet().encrypt(json.dumps(payload).encode("utf-8")).decode("ascii")


def verify_session_token(token: str) -> uuid.UUID:
    """Возвращает `user_id`; поднимает `InvalidSessionTokenError`, если
    токен подделан или истёк."""
    try:
        raw = _fernet().decrypt(token.encode("ascii"))
    except (InvalidToken, UnicodeEncodeError) as exc:
        raise InvalidSessionTokenError("Токен сессии недействителен") from exc

    payload = json.loads(raw)
    expires_at = datetime.fromisoformat(payload["expires_at"])
    if datetime.now(UTC) >= expires_at:
        raise InvalidSessionTokenError("Токен сессии истёк")
    return uuid.UUID(payload["user_id"])
