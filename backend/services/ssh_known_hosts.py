"""
Ключи хоста Git-сервера в формате OpenSSH `known_hosts` (раздел 19.3):
разбор, проверка вставленного администратором текста и отпечатки SHA256.
Без БД и без git — общее ядро учётных данных и SSH-операций.
"""

from __future__ import annotations

import asyncssh

from services.errors import ValidationError

_MARKER_PREFIX = "@"
_COMMENT_PREFIX = "#"
# Поля перед ключом: хосты, у строки с маркером (`@cert-authority`) — маркер и хосты.
_HOSTS_FIELDS = 1
_MARKER_HOSTS_FIELDS = 2
_SHOWN_LINE_LENGTH = 80
_FORBIDDEN_CHARACTER = "\x00"


def _line_key(line: str) -> asyncssh.SSHKey:
    """Ключ одной строки `[@маркер] хосты тип ключ [комментарий]`."""
    prefix_fields = _MARKER_HOSTS_FIELDS if line.startswith(_MARKER_PREFIX) else _HOSTS_FIELDS
    fields = line.split(None, prefix_fields)
    if len(fields) != prefix_fields + 1:
        raise ValidationError(f"Строка known_hosts не разобрана: {line[:_SHOWN_LINE_LENGTH]}")
    try:
        return asyncssh.import_public_key(fields[-1])
    except (ValueError, asyncssh.KeyImportError) as exc:
        raise ValidationError(
            f"Строка known_hosts не разобрана: {line[:_SHOWN_LINE_LENGTH]}",
        ) from exc


def known_hosts_keys(known_hosts: str) -> list[asyncssh.SSHKey]:
    """Ключи всех строк; пустые строки и комментарии пропускаются."""
    lines = (raw_line.strip() for raw_line in known_hosts.splitlines())
    return [_line_key(line) for line in lines if line and not line.startswith(_COMMENT_PREFIX)]


def validate_known_hosts(known_hosts: str) -> str:
    """
    Ключи Git-сервера, вставленные администратором (вывод `ssh-keyscan`):
    хотя бы одна строка с ключом. Возвращает нормализованный текст.
    """
    if _FORBIDDEN_CHARACTER in known_hosts:
        raise ValidationError("Недопустимые символы в known_hosts")
    if not known_hosts_keys(known_hosts):
        raise ValidationError("Укажите строки known_hosts с ключами Git-сервера")
    return known_hosts.strip() + "\n"


def known_hosts_fingerprints(known_hosts: str | None) -> list[str]:
    """
    Отпечатки SHA256 без повторов — администратор сверяет их с Git-сервером.
    """
    if not known_hosts:
        return []
    try:
        keys = known_hosts_keys(known_hosts)
    except ValidationError:
        # Сохранённое трекером не разбирается только при порче записи —
        # показ отпечатков не должен ронять список.
        return []
    return list(dict.fromkeys(key.get_fingerprint() for key in keys))
