"""
Публичный SSH-ключ sshfs-доступа (раздел 15.1 ТЗ, решение №16 плана).

Ключ хранится в формате строки `authorized_keys` OpenSSH: `тип base64
[комментарий]`. Проверка — без внешних зависимостей: тип из списка, строгий
base64 и совпадение типа, записанного внутри самого ключа, с объявленным
(иначе склеенная или обрезанная строка прошла бы проверку по префиксу).
"""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass

from services.errors import ValidationError

MAX_PUBLIC_KEY_LENGTH = 16 * 1024
_LENGTH_PREFIX_BYTES = 4
_FINGERPRINT_PREFIX = "SHA256:"
# Тип и тело ключа обязательны, комментарий — третье, необязательное поле.
_MIN_KEY_PARTS = 2
_KEY_PARTS_WITH_COMMENT = 3

ALLOWED_KEY_TYPES = frozenset(
    {
        "ssh-ed25519",
        "ssh-rsa",
        "ecdsa-sha2-nistp256",
        "ecdsa-sha2-nistp384",
        "ecdsa-sha2-nistp521",
        "sk-ssh-ed25519@openssh.com",
        "sk-ecdsa-sha2-nistp256@openssh.com",
    },
)


@dataclass(frozen=True, slots=True)
class ParsedSshKey:
    key_type: str
    blob: bytes
    comment: str | None

    def to_authorized_keys_line(self) -> str:
        encoded = base64.b64encode(self.blob).decode("ascii")
        parts = [self.key_type, encoded]
        if self.comment:
            parts.append(self.comment)
        return " ".join(parts)


def _embedded_key_type(blob: bytes) -> str | None:
    """Первое поле wire-формата ключа: uint32 длины и строка типа."""
    if len(blob) < _LENGTH_PREFIX_BYTES:
        return None
    length = int.from_bytes(blob[:_LENGTH_PREFIX_BYTES], "big")
    end = _LENGTH_PREFIX_BYTES + length
    if end > len(blob):
        return None
    try:
        return blob[_LENGTH_PREFIX_BYTES:end].decode("ascii")
    except UnicodeDecodeError:
        return None


def parse_public_key(text: str) -> ParsedSshKey:
    """Разбирает строку публичного ключа; `ValidationError` при любом нарушении формата."""
    stripped = text.strip()
    if not stripped:
        raise ValidationError("Публичный ключ пуст")
    if len(stripped) > MAX_PUBLIC_KEY_LENGTH:
        raise ValidationError("Публичный ключ слишком длинный")
    if "\n" in stripped or "\r" in stripped:
        raise ValidationError("Нужен ровно один ключ — одна строка")

    parts = stripped.split(maxsplit=_KEY_PARTS_WITH_COMMENT - 1)
    if len(parts) < _MIN_KEY_PARTS:
        raise ValidationError("Ожидается строка вида «ssh-ed25519 AAAA… комментарий»")
    key_type, encoded = parts[0], parts[1]
    if key_type not in ALLOWED_KEY_TYPES:
        raise ValidationError(f"Неподдерживаемый тип ключа: {key_type}")
    try:
        blob = base64.b64decode(encoded, validate=True)
    except ValueError as exc:  # binascii.Error и не-ASCII символы в строке
        raise ValidationError("Тело ключа — не base64") from exc
    if _embedded_key_type(blob) != key_type:
        raise ValidationError("Тело ключа не соответствует его типу")
    comment = parts[-1] if len(parts) == _KEY_PARTS_WITH_COMMENT else None
    return ParsedSshKey(key_type=key_type, blob=blob, comment=comment)


def fingerprint(blob: bytes) -> str:
    """Отпечаток в формате `ssh-keygen -lf`: SHA256 без хвостовых `=`."""
    digest = hashlib.sha256(blob).digest()
    return _FINGERPRINT_PREFIX + base64.b64encode(digest).decode("ascii").rstrip("=")


def fingerprint_of_public_key(text: str) -> str | None:
    """Отпечаток уже сохранённого ключа; `None`, если строка не разбирается."""
    try:
        return fingerprint(parse_public_key(text).blob)
    except ValidationError:
        return None
