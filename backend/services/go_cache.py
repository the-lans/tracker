"""
Кеши Go сессии задачи (раздел 19.3 ТЗ).

Сборочный кеш и кеш модулей лежат в каталоге сессии задачи
(`CLAUDE_SESSIONS_ROOT/<код>`), а не в `/tmp` контейнера: `/tmp` — tmpfs,
который засчитывается в лимит памяти контейнера. Кеш живёт между
перезапусками контейнера, не делится между задачами (кеш сборки адресуется
по хешу, общая запись открыла бы его для подмены) и удаляется:

- между нодами — целиком, если вместе с кешем модулей он больше
  `GO_CACHE_LIMIT_BYTES` (то же, что `go clean -cache`, но без контейнера);
- при переходе задачи в `done` и в `archived`.
"""

from __future__ import annotations

import asyncio
import os
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

from app_logging.config import get_logger
from services.claude_config import resolve_sessions_root
from services.task_codes import validate_task_code

if TYPE_CHECKING:
    from collections.abc import Callable

logger = get_logger("go_cache")

GO_CACHE_LIMIT_BYTES = 2 * 1024**3
BUILD_CACHE_DIRNAME = "go-cache"
MODULE_CACHE_DIRNAME = "go-mod"
# Модули Go сохраняет только для чтения: без прав на запись в каталоге
# `shutil.rmtree` не удалит и вложенные файлы.
_OWNER_RWX = 0o700


def go_cache_env(config_dir: Path) -> dict[str, str]:
    """Переменные Go контейнера сессии: кеши внутри каталога задачи `config_dir`."""
    return {
        "GOCACHE": str(config_dir / BUILD_CACHE_DIRNAME),
        "GOMODCACHE": str(config_dir / MODULE_CACHE_DIRNAME),
    }


def directory_size(path: Path) -> int:
    """Сумма размеров файлов каталога; ссылки не разворачиваются, отсутствующий путь — 0."""
    total = 0
    try:
        with os.scandir(path) as entries:
            for entry in entries:
                if entry.is_dir(follow_symlinks=False):
                    total += directory_size(Path(entry.path))
                else:
                    total += entry.stat(follow_symlinks=False).st_size
    except OSError:
        return total
    return total


def _make_removable(function: Callable[[str], object], path: str, _error: BaseException) -> None:
    """Обработчик `rmtree`: открывает каталог на запись и повторяет операцию."""
    parent = os.path.dirname(path)
    os.chmod(parent, _OWNER_RWX)
    function(path)


def _remove_tree(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path, onexc=_make_removable)


def _task_directory(task_code: str) -> Path:
    return resolve_sessions_root() / validate_task_code(task_code)


def _trim(directory: Path, *, limit: int) -> int:
    """Возвращает освобождённое число байт; кеш в пределах порога не трогается."""
    build = directory / BUILD_CACHE_DIRNAME
    modules = directory / MODULE_CACHE_DIRNAME
    build_size = directory_size(build)
    module_size = directory_size(modules)
    if build_size + module_size <= limit:
        return 0
    _remove_tree(build)
    freed = build_size
    # Кеш модулей, который один больше порога, пересоберётся скачиванием.
    if module_size > limit:
        _remove_tree(modules)
        freed += module_size
    return freed


async def trim_go_cache(task_code: str, *, limit: int = GO_CACHE_LIMIT_BYTES) -> int:
    """
    Между нодами: кеши Go задачи выше порога удаляются. Сбой файловой системы
    только логируется — пайплайн из-за кеша не останавливается.
    """
    directory = _task_directory(task_code)
    try:
        freed = await asyncio.to_thread(_trim, directory, limit=limit)
    except OSError:
        logger.warning("go_cache_trim_failed", task_code=task_code, exc_info=True)
        return 0
    if freed:
        logger.info("go_cache_trimmed", task_code=task_code, freed_bytes=freed, limit_bytes=limit)
    return freed


def _remove_all(directory: Path) -> None:
    for name in (BUILD_CACHE_DIRNAME, MODULE_CACHE_DIRNAME):
        _remove_tree(directory / name)


async def remove_go_cache(task_code: str) -> None:
    """Задача в `done` или `archived`: кеши Go удаляются целиком; отсутствие кеша — не ошибка."""
    directory = _task_directory(task_code)
    try:
        await asyncio.to_thread(_remove_all, directory)
    except OSError:
        logger.warning("go_cache_remove_failed", task_code=task_code, exc_info=True)
        return
    logger.info("go_cache_removed", task_code=task_code)
