"""Симметричное шифрование секретных значений (раздел 19.4, 3.2 ТЗ).

Ключ шифрования берётся из переменной окружения ``SECRET_ENCRYPTION_KEY``,
не из БД. Fernet требует urlsafe-base64 32-байтный ключ — сама переменная
окружения генерируется install.sh произвольной строкой (``openssl rand
-hex 32``), поэтому перед использованием мы детерминированно приводим её
к нужному Fernet-формату через SHA-256, а не требуем от администратора
знать формат Fernet-ключа.
"""

from __future__ import annotations

import base64
import hashlib
import os
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

__all__ = ["DecryptionError", "decrypt", "encrypt", "fernet_from_env"]

_ENCRYPTION_KEY_ENV = "SECRET_ENCRYPTION_KEY"


class DecryptionError(Exception):
    """Не удалось расшифровать значение — неверный ключ или повреждённые данные."""


def _derive_fernet_key(secret: str) -> bytes:
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


@lru_cache
def fernet_from_env(env_name: str) -> Fernet:
    """
    Fernet по секрету из переменной окружения ``env_name`` — произвольной
    строке, приводимой к ключу Fernet через SHA-256.
    """
    return Fernet(_derive_fernet_key(os.environ[env_name]))


def _fernet() -> Fernet:
    return fernet_from_env(_ENCRYPTION_KEY_ENV)


def encrypt(value: str) -> str:
    """Зашифровать значение для хранения в БД (``*_encrypted`` поля)."""
    return _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt(token: str) -> str:
    """Расшифровать значение, ранее полученное через :func:`encrypt`."""
    try:
        return _fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise DecryptionError("Не удалось расшифровать значение") from exc
