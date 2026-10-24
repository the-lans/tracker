"""
Код задачи (раздел 3.1 ТЗ): любой текст без пробелов — например, `RR-12345`
или ключ задачи Jira.

Код — имя каталога задачи в volume `task_repos` и `user_files` и часть рабочей
ветки `feature/<код>`, поэтому дополнительно запрещено всё, что выводит путь
за пределы каталога или недопустимо в имени ветки git
(`git check-ref-format`).
"""

from __future__ import annotations

import re

from services.errors import ValidationError

MAX_TASK_CODE_LENGTH = 64
# Пробельные и управляющие символы, разделители пути и символы, запрещённые
# в именах веток git.
_FORBIDDEN_CHARACTERS = re.compile(r"[\s\x00-\x1f\x7f/\\~^:?*\[]")
_FORBIDDEN_SEQUENCES = ("..", "@{")
_FORBIDDEN_PREFIXES = ("-", ".")
_FORBIDDEN_SUFFIXES = (".", ".lock")


def validate_task_code(code: str) -> str:
    """Возвращает код без изменений или поднимает `ValidationError` с причиной."""
    if not code:
        raise ValidationError("Укажите код задачи")
    if len(code) > MAX_TASK_CODE_LENGTH:
        raise ValidationError(f"Код задачи длиннее {MAX_TASK_CODE_LENGTH} символов")
    if _FORBIDDEN_CHARACTERS.search(code):
        raise ValidationError(
            "Код задачи — текст без пробелов и символов / \\ ~ ^ : ? * [",
        )
    if any(sequence in code for sequence in _FORBIDDEN_SEQUENCES):
        raise ValidationError("Код задачи не может содержать «..» и «@{»")
    if code.startswith(_FORBIDDEN_PREFIXES) or code.endswith(_FORBIDDEN_SUFFIXES):
        raise ValidationError(
            "Код задачи не может начинаться с «-» или «.» и заканчиваться на «.» или «.lock»",
        )
    return code
