"""
Артефакты задачи (раздел 14.3 ТЗ, решение №18 плана): файлы, которые
пользователь загружает через трекер или SFTP-шлюз, а агент читает и
сохраняет туда результат. Хранятся в volume `user_files`
(`/data/user-files/<код задачи>/`), отдельно от репозиториев: очистка
репозиториев их не трогает.

`resolve_inside` — общая проверка пути для API и SFTP-шлюза: путь задаётся
относительно каталога, а его реальное расположение (после разрешения
символических ссылок) обязано остаться внутри этого каталога.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from services.errors import NotFoundError, PayloadTooLargeError, ValidationError

_USER_FILES_ROOT_ENV_VAR = "TRACKER_USER_FILES_ROOT"
_DEFAULT_USER_FILES_ROOT = "tracker/user-files"
_MAX_UPLOAD_ENV_VAR = "ARTIFACT_MAX_UPLOAD_MB"
DEFAULT_MAX_UPLOAD_MB = 100
_BYTES_PER_MB = 1024 * 1024
# Ограничение ответа списка: каталог артефактов пишет и агент.
MAX_LISTED_ARTIFACTS = 1000
# Незавершённая загрузка: в списке не показывается, на месте файла не лежит.
_UPLOAD_TEMP_PREFIX = ".tracker-upload-"


@dataclass(frozen=True, slots=True)
class ArtifactInfo:
    path: str
    size: int
    modified_at: datetime


def resolve_user_files_root() -> Path:
    """Корень артефактов — volume `user_files` (раздел 14.3, 20.4)."""
    return Path(os.environ.get(_USER_FILES_ROOT_ENV_VAR, _DEFAULT_USER_FILES_ROOT))


def task_artifacts_dir(task_code: str) -> Path:
    """Каталог артефактов задачи; создаётся при первом обращении."""
    directory = resolve_user_files_root() / task_code
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def task_artifacts_path(task_code: str) -> str:
    """`{{task.artifacts_path}}` (раздел 5): абсолютный путь с завершающим "/"."""
    return f"{(resolve_user_files_root() / task_code).resolve()}/"


def max_upload_bytes() -> int:
    return int(os.environ.get(_MAX_UPLOAD_ENV_VAR, DEFAULT_MAX_UPLOAD_MB)) * _BYTES_PER_MB


def resolve_inside(base: Path, relative: str) -> Path:
    """
    Реальный путь `relative` внутри `base`; пустой путь или "." — сам `base`.
    Абсолютный путь, "..", NUL и выход наружу через символическую ссылку —
    `ValidationError`.
    """
    pure = PurePosixPath(relative)
    if "\0" in relative or pure.is_absolute() or ".." in pure.parts:
        raise ValidationError(f"Недопустимый путь: {relative!r}")
    real_base = Path(os.path.realpath(base))
    target = Path(os.path.realpath(real_base.joinpath(*pure.parts)))
    if target != real_base and real_base not in target.parents:
        raise ValidationError(f"Путь {relative!r} выходит за пределы каталога")
    return target


def _artifact_target(task_code: str, relative: str) -> Path:
    directory = task_artifacts_dir(task_code)
    target = resolve_inside(directory, relative)
    if target == Path(os.path.realpath(directory)):
        raise ValidationError("Не указано имя файла")
    return target


def _info(directory: Path, path: Path) -> ArtifactInfo:
    stat = path.stat()
    return ArtifactInfo(
        path=path.relative_to(directory).as_posix(),
        size=stat.st_size,
        modified_at=datetime.fromtimestamp(stat.st_mtime, tz=UTC),
    )


def list_artifacts(task_code: str) -> list[ArtifactInfo]:
    """Обычные файлы каталога артефактов, по пути; символические ссылки не обходятся."""
    directory = Path(os.path.realpath(task_artifacts_dir(task_code)))
    files: list[Path] = []
    for current, dirnames, filenames in os.walk(directory):
        dirnames.sort()
        for name in sorted(filenames):
            path = Path(current) / name
            if name.startswith(_UPLOAD_TEMP_PREFIX) or path.is_symlink():
                continue
            if path.is_file():
                files.append(path)
    files.sort()
    return [_info(directory, path) for path in files[:MAX_LISTED_ARTIFACTS]]


async def save_artifact(
    task_code: str,
    relative: str,
    chunks: AsyncIterator[bytes],
    *,
    max_bytes: int,
) -> ArtifactInfo:
    """
    Пишет файл во временный рядом и заменяет им цель только после полной
    загрузки: оборванная или слишком большая загрузка не портит прежний файл.
    """
    target = _artifact_target(task_code, relative)
    if target.is_dir():
        raise ValidationError(f"{relative!r} — каталог, а не файл")
    target.parent.mkdir(parents=True, exist_ok=True)
    temp_path = target.parent / f"{_UPLOAD_TEMP_PREFIX}{uuid.uuid4().hex}"
    written = 0
    try:
        with temp_path.open("wb") as temp_file:
            async for chunk in chunks:
                written += len(chunk)
                if written > max_bytes:
                    limit_mb = max_bytes // _BYTES_PER_MB
                    raise PayloadTooLargeError(f"Файл больше допустимых {limit_mb} МБ")
                temp_file.write(chunk)
        temp_path.replace(target)
    finally:
        temp_path.unlink(missing_ok=True)
    return _info(Path(os.path.realpath(task_artifacts_dir(task_code))), target)


def artifact_file(task_code: str, relative: str) -> Path:
    target = _artifact_target(task_code, relative)
    if not target.is_file():
        raise NotFoundError(f"Артефакт {relative!r} не найден")
    return target


def delete_artifact(task_code: str, relative: str) -> None:
    artifact_file(task_code, relative).unlink()
