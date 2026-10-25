"""
Артефакты задачи (раздел 14.3 ТЗ, решение №18 плана): файлы, которые
пользователь загружает через трекер или SFTP-шлюз, а агент читает и
сохраняет туда результат. Хранятся в volume `user_files`
(`/data/user-files/<код задачи>/`), отдельно от репозиториев: очистка
репозиториев их не трогает.

`resolve_inside` — общая проверка пути для API и SFTP-шлюза: путь задаётся
относительно каталога, а его реальное расположение (после разрешения
символических ссылок) обязано остаться внутри этого каталога.
`resolve_entry` — то же для операций над самой записью каталога (удаление,
перенос, замена): последний элемент не разыменовывается, поэтому они
действуют на символическую ссылку, а не на файл, куда она указывает.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from services.errors import NotFoundError, PayloadTooLargeError, ValidationError
from services.task_codes import validate_task_code

_USER_FILES_ROOT_ENV_VAR = "TRACKER_USER_FILES_ROOT"
_DEFAULT_USER_FILES_ROOT = "tracker/user-files"
_MAX_UPLOAD_ENV_VAR = "ARTIFACT_MAX_UPLOAD_MB"
DEFAULT_MAX_UPLOAD_MB = 100
_BYTES_PER_MB = 1024 * 1024
# Ограничение ответа списка: каталог артефактов пишет и агент.
MAX_LISTED_ARTIFACTS = 1000
# Незавершённая загрузка: в списке не показывается, на месте файла не лежит.
_UPLOAD_TEMP_PREFIX = ".tracker-upload-"
_NO_FILE_NAME_MESSAGE = "Не указано имя файла"


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
    directory = resolve_user_files_root() / validate_task_code(task_code)
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def task_artifacts_path(task_code: str) -> str:
    """`{{task.artifacts_path}}` (раздел 5): абсолютный путь с завершающим "/"."""
    return f"{(resolve_user_files_root() / validate_task_code(task_code)).resolve()}/"


def max_upload_bytes() -> int:
    return int(os.environ.get(_MAX_UPLOAD_ENV_VAR, DEFAULT_MAX_UPLOAD_MB)) * _BYTES_PER_MB


def _checked_relative(relative: str) -> PurePosixPath:
    pure = PurePosixPath(relative)
    if "\0" in relative or pure.is_absolute() or ".." in pure.parts:
        raise ValidationError(f"Недопустимый путь: {relative!r}")
    return pure


def resolve_inside(base: Path, relative: str) -> Path:
    """
    Реальный путь `relative` внутри `base`; пустой путь или "." — сам `base`.
    Абсолютный путь, "..", NUL и выход наружу через символическую ссылку —
    `ValidationError`.
    """
    pure = _checked_relative(relative)
    real_base = Path(os.path.realpath(base))
    target = Path(os.path.realpath(real_base.joinpath(*pure.parts)))
    if target != real_base and real_base not in target.parents:
        raise ValidationError(f"Путь {relative!r} выходит за пределы каталога")
    return target


def resolve_entry(base: Path, relative: str) -> Path:
    """
    Запись `relative` внутри `base`: родитель проверяется `resolve_inside`,
    последний элемент остаётся как есть. Пустой путь — `ValidationError`.
    """
    pure = _checked_relative(relative)
    if not pure.name:
        raise ValidationError(_NO_FILE_NAME_MESSAGE)
    return resolve_inside(base, str(pure.parent)) / pure.name


def _artifact_target(task_code: str, relative: str) -> Path:
    directory = task_artifacts_dir(task_code)
    target = resolve_inside(directory, relative)
    if target == Path(os.path.realpath(directory)):
        raise ValidationError(_NO_FILE_NAME_MESSAGE)
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
    Символическая ссылка с тем же путём заменяется сама, её цель не меняется.
    """
    target = resolve_entry(task_artifacts_dir(task_code), relative)
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


def _not_found(relative: str) -> NotFoundError:
    return NotFoundError(f"Артефакт {relative!r} не найден")


def artifact_file(task_code: str, relative: str) -> Path:
    target = _artifact_target(task_code, relative)
    if not target.is_file():
        raise _not_found(relative)
    return target


def delete_artifact(task_code: str, relative: str) -> None:
    """Символическая ссылка удаляется сама, файл, куда она указывает, остаётся."""
    entry = resolve_entry(task_artifacts_dir(task_code), relative)
    if not (entry.is_symlink() or entry.is_file()):
        raise _not_found(relative)
    entry.unlink()
