"""
Монтирование каталогов задачи в контейнеры, которые запускает воркер:
script-ноды (`services/nodes/script.py`) и контейнер сессии
(`services/session_container.py`), раздел 19.3 ТЗ.

Воркер в продакшене сам работает в контейнере, а `docker run` исполняет
демон хоста: путь `/data/repos/...` из контейнера воркера демону не виден.
Поэтому воркер один раз смотрит `docker inspect` своего контейнера, что
смонтировано в корень (репозиториев, артефактов, LLM-аккаунтов): volume —
каталог задачи монтируется его подпутём (Docker Engine 26+), каталог хоста —
подкаталогом этого каталога. Если воркер не в контейнере (тесты, запуск на
хосте), путь монтируется как есть.
"""

from __future__ import annotations

import asyncio
import socket
from dataclasses import dataclass
from pathlib import Path

from app_logging.config import get_logger

logger = get_logger("docker_mounts")

_VOLUME_MOUNT = "volume"
# Docker создаёт этот файл в каждом контейнере.
_CONTAINER_MARKER = Path("/.dockerenv")


@dataclass(frozen=True, slots=True)
class RootMount:
    """Что демон Docker смонтировал в корень каталогов задач контейнера воркера."""

    type: str
    name: str
    source: str


# Монтирование контейнера не меняется, пока жив процесс воркера: кешируется
# только найденное, неудачная проверка повторяется при следующем запуске.
_root_mount_cache: dict[str, RootMount] = {}


class RepositoryMountError(RuntimeError):
    """Воркер в контейнере, но не удалось узнать, что смонтировано в корень директорий задач."""


def parse_root_mount(line: str) -> RootMount | None:
    """Строка ``<type> <name> <source>`` из `docker inspect`; пусто — нет монтирования."""
    parts = line.strip("\n").split(" ", 2)
    if len(parts) != 3 or not parts[0]:
        return None
    mount_type, name, source = parts
    return RootMount(type=mount_type, name=name, source=source)


async def _inspect_root_mount(root: Path) -> RootMount | None:
    """Монтирование `root` в своём контейнере; `None` — не в контейнере."""
    destination = str(root.resolve())
    template = (
        "{{range .Mounts}}{{if eq .Destination " + f'"{destination}"'
        + "}}{{.Type}} {{.Name}} {{.Source}}{{end}}{{end}}"
    )
    process = await asyncio.create_subprocess_exec(
        "docker",
        "inspect",
        "--format",
        template,
        socket.gethostname(),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    stdout, _ = await process.communicate()
    if process.returncode != 0:
        return None
    return parse_root_mount(stdout.decode())


async def resolve_root_mount(root: Path) -> RootMount | None:
    """
    `None` — воркер не в контейнере, путь монтируется как есть. В контейнере
    без найденного монтирования путь хоста демону не виден, поэтому вместо
    тихой подмены — ошибка, а проверка повторится при следующем запуске.
    """
    key = str(root.resolve())
    if key in _root_mount_cache:
        return _root_mount_cache[key]
    mount = await _inspect_root_mount(root)
    if mount is not None:
        _root_mount_cache[key] = mount
        logger.info("root_mount_resolved", root=key, mount=str(mount))
        return mount
    if _CONTAINER_MARKER.exists():
        message = (
            f"Не удалось определить через `docker inspect`, что смонтировано в {root} "
            "контейнера воркера"
        )
        raise RepositoryMountError(message)
    return None


def subpath_mount_args(path: Path, root: Path, root_mount: RootMount | None) -> list[str]:
    """Аргументы `docker run`, монтирующие только каталог задачи `path` из `root` (раздел 19.3)."""
    if root_mount is None:
        return ["-v", f"{path}:{path}:rw"]
    real_root = root.resolve()
    try:
        subpath = path.resolve().relative_to(real_root)
    except ValueError as exc:
        message = f"Директория {path} вне корня {real_root}"
        raise ValueError(message) from exc
    if subpath == Path():
        message = f"Директория задачи не может совпадать с корнем {real_root}"
        raise ValueError(message)
    if root_mount.type == _VOLUME_MOUNT:
        return [
            "--mount",
            f"type=volume,src={root_mount.name},dst={path},"
            f"volume-subpath={subpath.as_posix()}",
        ]
    host_path = Path(root_mount.source) / subpath
    return ["-v", f"{host_path}:{path}:rw"]


async def mount_args(path: Path, root: Path) -> list[str]:
    """Каталог задачи `path` из корня `root` — с учётом того, где работает воркер."""
    return subpath_mount_args(path, root, await resolve_root_mount(root))
