"""
Поля репозитория (раздел 3.1 ТЗ), которые попадают в файловую систему и в
командную строку git: `name` — каталог клона внутри каталога задачи,
`git_url` — аргумент `git clone`, базовая ветка задачи — аргумент
`git clone --branch` и `git fetch`.

Значение, начинающееся с `-`, git принял бы за опцию (`--upload-pack=…`
выполняет команду), а `..` в имени вывело бы клон за пределы задачи.
"""

from __future__ import annotations

import re

from services.errors import ValidationError

_NAME_PATTERN = re.compile(r"[A-Za-z0-9._-]+")
_RESERVED_NAMES = frozenset({".", ".."})
# `ssh://`, `https://`, `http://` или scp-форма `user@host:path`.
_URL_SCHEME_PATTERN = re.compile(r"(ssh|https?)://[^\s/@]+(@[^\s/]+)?/\S+")
_SCP_PATTERN = re.compile(r"[A-Za-z0-9._-]+@[A-Za-z0-9.-]+:[^\s]+")
# Правила `git check-ref-format` для имени ветки.
_BRANCH_FORBIDDEN_CHARACTERS = re.compile(r"[\s\x00-\x1f\x7f\\~^:?*\[]")
_BRANCH_FORBIDDEN_SEQUENCES = ("..", "@{", "//", "/.")


def validate_repository_name(name: str) -> str:
    if not _NAME_PATTERN.fullmatch(name) or name in _RESERVED_NAMES or name.startswith("-"):
        raise ValidationError(
            "Имя репозитория — латинские буквы, цифры, «.», «_» и «-», "
            "не «.» или «..» и не с «-» в начале",
        )
    return name


def validate_git_url(git_url: str) -> str:
    if git_url.startswith("-") or not (
        _URL_SCHEME_PATTERN.fullmatch(git_url) or _SCP_PATTERN.fullmatch(git_url)
    ):
        raise ValidationError(
            "Адрес репозитория — ssh://, https:// или вида git@host:group/project.git",
        )
    return git_url


def validate_branch_name(branch: str) -> str:
    """Базовая ветка репозитория задачи (раздел 3.1, `task_repositories.base_branch`)."""
    if (
        not branch
        or branch.startswith(("-", ".", "/"))
        or branch.endswith(("/", ".", ".lock"))
        or _BRANCH_FORBIDDEN_CHARACTERS.search(branch)
        or any(sequence in branch for sequence in _BRANCH_FORBIDDEN_SEQUENCES)
    ):
        raise ValidationError(f"Недопустимое имя ветки: {branch!r}")
    return branch
