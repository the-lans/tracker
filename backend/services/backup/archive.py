"""
Архив каталога volume для копии (раздел 20.4 ТЗ) — `tar.gz` в формате
`tar czf <имя>.tar.gz -C <каталог> .`, который распаковывает
`install.sh --restore`. Права, владельцы и симлинки сохраняются.

Данные копируются на живом сервере, поэтому каждый файл сначала читается
целиком во временный файл, а размер и время изменения сверяются до и после
чтения: файл, который менялся во время чтения, перечитывается после паузы.
Файл, занятый операцией git (рядом лежит `<файл>.lock`), ждёт снятия
блокировки. Не дождались за несколько попыток или файл не читается —
пропуск с причиной: копия остаётся полезной, а пропуск виден администратору.
Сами `*.lock` внутри `.git` не копируются: после восстановления их никто не
держит, а оставшийся замок помешал бы git.
"""

from __future__ import annotations

import fnmatch
import os
import stat
import tarfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import SpooledTemporaryFile

from app_logging.config import get_logger
from services.backup.files import READ_CHUNK_BYTES

logger = get_logger("backup_archive")

DEFAULT_READ_ATTEMPTS = 3
DEFAULT_RETRY_DELAY_SECONDS = 2.0
GZIP_COMPRESS_LEVEL = 6
_SPOOL_MAX_BYTES = 32 * 1024 * 1024
_GIT_DIR = ".git"
_LOCK_SUFFIX = ".lock"
_ROOT_ARCNAME = "."

REASON_CHANGING = "файл менялся во время чтения"
REASON_LOCKED = "файл занят операцией git"
REASON_UNREADABLE = "файл не читается"
REASON_DIRECTORY_UNREADABLE = "каталог не читается"


@dataclass(frozen=True, slots=True)
class SkippedFile:
    component: str
    path: str
    reason: str

    def as_dict(self) -> dict[str, str]:
        return {"component": self.component, "path": self.path, "reason": self.reason}


@dataclass(slots=True)
class ArchiveStats:
    files: int = 0
    bytes: int = 0
    skipped: list[SkippedFile] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class ArchiveOptions:
    excludes: tuple[str, ...] = ()
    attempts: int = DEFAULT_READ_ATTEMPTS
    retry_delay_seconds: float = DEFAULT_RETRY_DELAY_SECONDS
    # Каталог временных файлов чтения (staging, а не /tmp контейнера).
    spool_dir: Path | None = None


def _in_git_dir(relative: str) -> bool:
    return _GIT_DIR in relative.split("/")


def _is_git_lock(relative: str) -> bool:
    return relative.endswith(_LOCK_SUFFIX) and _in_git_dir(relative)


def _is_excluded(relative: str, excludes: tuple[str, ...]) -> bool:
    return any(fnmatch.fnmatchcase(relative, pattern) for pattern in excludes)


def _arcname(relative: str) -> str:
    return f"./{relative}"


class _DirectoryArchiver:
    def __init__(
        self,
        tar: tarfile.TarFile,
        *,
        root: Path,
        component: str,
        options: ArchiveOptions,
    ) -> None:
        self._tar = tar
        self._root = root
        self._component = component
        self._options = options
        self.stats = ArchiveStats()

    def _skip(self, relative: str, reason: str) -> None:
        self.stats.skipped.append(SkippedFile(self._component, relative, reason))
        logger.warning(
            "backup_file_skipped",
            component=self._component,
            path=relative,
            reason=reason,
        )

    def _pause(self) -> None:
        if self._options.retry_delay_seconds > 0:
            time.sleep(self._options.retry_delay_seconds)

    def _locked(self, path: Path, relative: str) -> bool:
        return _in_git_dir(relative) and path.with_name(path.name + _LOCK_SUFFIX).exists()

    def _read_stable(self, path: Path) -> SpooledTemporaryFile[bytes] | None:
        """Содержимое, если файл не менялся во время чтения; иначе `None`."""
        before = os.lstat(path)
        spool: SpooledTemporaryFile[bytes] = SpooledTemporaryFile(
            max_size=_SPOOL_MAX_BYTES,
            dir=str(self._options.spool_dir) if self._options.spool_dir else None,
        )
        with path.open("rb") as source:
            while chunk := source.read(READ_CHUNK_BYTES):
                spool.write(chunk)
        after = os.lstat(path)
        unchanged = (before.st_size, before.st_mtime_ns) == (
            after.st_size,
            after.st_mtime_ns,
        ) and spool.tell() == after.st_size
        if unchanged:
            spool.seek(0)
            return spool
        spool.close()
        return None

    def add_file(self, path: Path, relative: str) -> None:
        reason = REASON_UNREADABLE
        for attempt in range(1, self._options.attempts + 1):
            if attempt > 1:
                self._pause()
            if self._locked(path, relative):
                reason = REASON_LOCKED
                continue
            try:
                content = self._read_stable(path)
            except FileNotFoundError:
                # Удалён между обходом и чтением — его просто больше нет.
                return
            except OSError:
                reason = REASON_UNREADABLE
                continue
            if content is None:
                reason = REASON_CHANGING
                continue
            with content:
                self._add_content(path, relative, content)
            return
        self._skip(relative, reason)

    def _add_content(
        self,
        path: Path,
        relative: str,
        content: SpooledTemporaryFile[bytes],
    ) -> None:
        info = self._tar.gettarinfo(str(path), arcname=_arcname(relative))
        if info.islnk():
            # Жёсткая ссылка на уже добавленный файл: содержимое не дублируется.
            self._tar.addfile(info)
            return
        content.seek(0, os.SEEK_END)
        info.size = content.tell()
        content.seek(0)
        self._tar.addfile(info, content)
        self.stats.files += 1
        self.stats.bytes += info.size

    def add_entry(self, path: Path, relative: str) -> bool:
        """Добавляет запись каталога; `True` — в каталог нужно спускаться."""
        try:
            mode = os.lstat(path).st_mode
        except FileNotFoundError:
            return False
        if stat.S_ISLNK(mode):
            self._tar.add(str(path), arcname=_arcname(relative), recursive=False)
            return False
        if stat.S_ISDIR(mode):
            if _is_excluded(relative, self._options.excludes):
                return False
            self._tar.add(str(path), arcname=_arcname(relative), recursive=False)
            return True
        if stat.S_ISREG(mode) and not _is_git_lock(relative):
            self.add_file(path, relative)
        # Сокеты и каналы — состояние работающих процессов, не данные.
        return False

    def walk(self) -> None:
        self._tar.add(str(self._root), arcname=_ROOT_ARCNAME, recursive=False)
        pending = [""]
        while pending:
            relative_dir = pending.pop()
            directory = self._root / relative_dir if relative_dir else self._root
            try:
                names = sorted(os.listdir(directory))
            except OSError:
                self._skip(relative_dir or _ROOT_ARCNAME, REASON_DIRECTORY_UNREADABLE)
                continue
            descend: list[str] = []
            for name in names:
                relative = f"{relative_dir}/{name}" if relative_dir else name
                if self.add_entry(directory / name, relative):
                    descend.append(relative)
            pending.extend(reversed(descend))


def archive_directory(
    root: Path,
    target: Path,
    *,
    component: str,
    options: ArchiveOptions,
) -> ArchiveStats:
    """Пишет `target` (`tar.gz`) из содержимого `root`; отдаёт число файлов и пропуски."""
    with tarfile.open(target, "w:gz", compresslevel=GZIP_COMPRESS_LEVEL) as tar:
        archiver = _DirectoryArchiver(tar, root=root, component=component, options=options)
        archiver.walk()
    logger.info(
        "backup_component_archived",
        component=component,
        files=archiver.stats.files,
        skipped=len(archiver.stats.skipped),
    )
    return archiver.stats
