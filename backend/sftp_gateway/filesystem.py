"""
Виртуальная файловая система SFTP-шлюза (раздел 14.3, 19.2, 19.3 ТЗ).

    /                         — задачи, видимые пользователю (`user` — свои, `admin` — все)
    /<код>/repos/...          — директория репозиториев задачи, только чтение
    /<код>/artifacts/...      — артефакты задачи, чтение и запись

Каждая операция заново проверяет вход и доступ к задаче
(`services/sftp_access.py`): смена ключа, блокировка пользователя и удаление
задачи действуют сразу. Реальный путь вычисляет `resolve_inside`: выйти за
каталог задачи нельзя ни через "..", ни через символическую ссылку. Ссылки
внутри каталога клиенту показываются как сами файлы, ссылки наружу — не
показываются вовсе. Удаление и перенос действуют на саму ссылку
(`resolve_entry`), а не на её цель. Создавать ссылки нельзя.
"""

from __future__ import annotations

import os
import posixpath
import stat
from collections.abc import AsyncIterator
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

import asyncssh
from asyncssh import SFTPAttrs, SFTPName

from services.errors import ValidationError
from services.sftp_access import SftpLogin, is_task_visible, list_visible_task_codes
from services.task_artifacts import resolve_entry, resolve_inside

if TYPE_CHECKING:
    from asyncssh import SSHServerChannel

    from sftp_gateway.config import GatewayConfig, SessionFactory

_ROOT = b"/"
_DIR_PERMISSIONS = stat.S_IFDIR | 0o555
_SPECIAL_ENTRIES = (b".", b"..")
_WRITE_FLAGS = asyncssh.FXF_WRITE | asyncssh.FXF_APPEND | asyncssh.FXF_CREAT | asyncssh.FXF_TRUNC
_WRITE_ACCESS = (
    asyncssh.ACE4_WRITE_DATA | asyncssh.ACE4_APPEND_DATA | asyncssh.ACE4_WRITE_ATTRIBUTES
)
_READ_ONLY_MESSAGE = "Только чтение: записывать можно в artifacts/"


class Area(StrEnum):
    REPOS = "repos"
    ARTIFACTS = "artifacts"


@dataclass(frozen=True, slots=True)
class Target:
    """Разобранный путь клиента: `code` и `area` пусты у виртуальных каталогов."""

    code: str | None = None
    area: Area | None = None
    real: Path | None = None
    relative: str = ""

    @property
    def is_entry(self) -> bool:
        """Файл или каталог внутри области, а не виртуальный каталог."""
        return self.real is not None and bool(self.relative)


def normalize(path: bytes) -> bytes:
    """Абсолютный нормализованный путь; ".." выше корня остаётся в корне."""
    return posixpath.normpath(posixpath.join(_ROOT, path))


def _virtual_dir_attrs() -> SFTPAttrs:
    return SFTPAttrs(type=asyncssh.FILEXFER_TYPE_DIRECTORY, permissions=_DIR_PERMISSIONS, size=0)


class TaskSftpServer(asyncssh.SFTPServer):
    """SFTP-сессия одного пользователя; доступ к БД — через `session_factory`."""

    def __init__(
        self,
        chan: SSHServerChannel[bytes],
        *,
        login: SftpLogin,
        session_factory: SessionFactory,
        config: GatewayConfig,
    ) -> None:
        super().__init__(chan)
        self._login = login
        self._session_factory = session_factory
        self._config = config
        self._read_only_files: set[int] = set()

    def _area_root(self, code: str, area: Area) -> Path:
        if area is Area.REPOS:
            return self._config.repos_root / code
        directory = self._config.user_files_root / code
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    async def _visible_codes(self) -> list[str]:
        async with self._session_factory() as db_session:
            return await list_visible_task_codes(db_session, login=self._login)

    async def _target(self, path: bytes, *, entry: bool = False) -> Target:
        """`entry` — путь самой записи каталога, без разыменования последнего элемента."""
        parts = [os.fsdecode(part) for part in normalize(path).split(b"/") if part]
        if not parts:
            return Target()
        code = parts[0]
        async with self._session_factory() as db_session:
            visible = await is_task_visible(db_session, login=self._login, code=code)
        if not visible:
            raise asyncssh.SFTPNoSuchFile("Нет такой задачи")
        if len(parts) == 1:
            return Target(code=code)
        try:
            area = Area(parts[1])
        except ValueError as exc:
            raise asyncssh.SFTPNoSuchFile("Нет такого каталога") from exc
        relative = "/".join(parts[2:])
        resolve = resolve_entry if entry and relative else resolve_inside
        try:
            real = resolve(self._area_root(code, area), relative)
        except ValidationError as exc:
            raise asyncssh.SFTPPermissionDenied(exc.message) from exc
        return Target(code=code, area=area, real=real, relative=relative)

    async def _writable(self, path: bytes, *, entry: bool = False) -> Target:
        target = await self._target(path, entry=entry)
        if target.area is not Area.ARTIFACTS or not target.is_entry:
            raise asyncssh.SFTPPermissionDenied(_READ_ONLY_MESSAGE)
        return target

    @staticmethod
    def _real_bytes(target: Target) -> bytes:
        assert target.real is not None
        return os.fsencode(target.real)

    # --- Чтение -----------------------------------------------------------

    def realpath(self, path: bytes) -> bytes:
        return normalize(path)

    async def stat(self, path: bytes) -> SFTPAttrs | os.stat_result:
        target = await self._target(path)
        if target.real is None or (not target.is_entry and not target.real.exists()):
            return _virtual_dir_attrs()
        return os.stat(target.real)

    async def lstat(self, path: bytes) -> SFTPAttrs | os.stat_result:
        """Ссылки внутри области показываются как сами файлы (см. docstring модуля)."""
        return await self.stat(path)

    async def scandir(self, path: bytes) -> AsyncIterator[SFTPName]:
        target = await self._target(path)
        for special in _SPECIAL_ENTRIES:
            yield SFTPName(special, attrs=_virtual_dir_attrs())
        if target.code is None:
            for code in await self._visible_codes():
                yield SFTPName(os.fsencode(code), attrs=_virtual_dir_attrs())
            return
        if target.area is None:
            for area in Area:
                yield SFTPName(os.fsencode(area.value), attrs=_virtual_dir_attrs())
            return
        assert target.real is not None
        if not target.real.is_dir():
            return
        area_root = self._area_root(target.code, target.area)
        for name in sorted(os.listdir(target.real)):
            entry_relative = posixpath.join(target.relative, name)
            try:
                real = resolve_inside(area_root, entry_relative)
                attrs = SFTPAttrs.from_local(os.stat(real))
            except (ValidationError, OSError):
                continue
            yield SFTPName(os.fsencode(name), attrs=attrs)

    def readlink(self, path: bytes) -> bytes:
        raise asyncssh.SFTPNoSuchFile("Символические ссылки не показываются")

    async def statvfs(self, path: bytes) -> os.statvfs_result:
        self._config.user_files_root.mkdir(parents=True, exist_ok=True)
        return os.statvfs(self._config.user_files_root)

    # --- Открытие файлов ----------------------------------------------------

    async def _open_target(self, path: bytes, *, write: bool) -> Target:
        target = await (self._writable(path) if write else self._target(path))
        if not target.is_entry:
            raise asyncssh.SFTPFileIsADirectory("Это каталог")
        return target

    def _remember(self, file_obj: object, target: Target) -> object:
        if target.area is Area.REPOS:
            self._read_only_files.add(id(file_obj))
        return file_obj

    async def open(self, path: bytes, pflags: int, attrs: SFTPAttrs) -> object:
        target = await self._open_target(path, write=bool(pflags & _WRITE_FLAGS))
        file_obj = super().open(self._real_bytes(target), pflags, attrs)
        return self._remember(file_obj, target)

    async def open56(
        self,
        path: bytes,
        desired_access: int,
        flags: int,
        attrs: SFTPAttrs,
    ) -> object:
        disposition = flags & asyncssh.FXF_ACCESS_DISPOSITION
        write = bool(desired_access & _WRITE_ACCESS) or disposition != asyncssh.FXF_OPEN_EXISTING
        target = await self._open_target(path, write=write)
        file_obj = super().open56(self._real_bytes(target), desired_access, flags, attrs)
        return self._remember(file_obj, target)

    def close(self, file_obj: object) -> None:
        self._read_only_files.discard(id(file_obj))
        super().close(file_obj)

    def fsetstat(self, file_obj: object, attrs: SFTPAttrs) -> None:
        if id(file_obj) in self._read_only_files:
            raise asyncssh.SFTPPermissionDenied(_READ_ONLY_MESSAGE)
        super().fsetstat(file_obj, attrs)

    # --- Изменения: только в artifacts/ ------------------------------------

    async def setstat(self, path: bytes, attrs: SFTPAttrs) -> None:
        super().setstat(self._real_bytes(await self._writable(path)), attrs)

    async def lsetstat(self, path: bytes, attrs: SFTPAttrs) -> None:
        super().lsetstat(self._real_bytes(await self._writable(path)), attrs)

    async def remove(self, path: bytes) -> None:
        super().remove(self._real_bytes(await self._writable(path, entry=True)))

    async def mkdir(self, path: bytes, attrs: SFTPAttrs) -> None:
        super().mkdir(self._real_bytes(await self._writable(path, entry=True)), attrs)

    async def rmdir(self, path: bytes) -> None:
        super().rmdir(self._real_bytes(await self._writable(path, entry=True)))

    async def _rename_targets(self, oldpath: bytes, newpath: bytes) -> tuple[bytes, bytes]:
        old = await self._writable(oldpath, entry=True)
        new = await self._writable(newpath, entry=True)
        if old.code != new.code:
            raise asyncssh.SFTPPermissionDenied("Переносить файлы между задачами нельзя")
        return self._real_bytes(old), self._real_bytes(new)

    async def rename(self, oldpath: bytes, newpath: bytes) -> None:
        super().rename(*await self._rename_targets(oldpath, newpath))

    async def posix_rename(self, oldpath: bytes, newpath: bytes) -> None:
        super().posix_rename(*await self._rename_targets(oldpath, newpath))

    def symlink(self, oldpath: bytes, newpath: bytes) -> None:
        raise asyncssh.SFTPPermissionDenied("Создавать ссылки нельзя")

    def link(self, oldpath: bytes, newpath: bytes) -> None:
        raise asyncssh.SFTPPermissionDenied("Создавать ссылки нельзя")
