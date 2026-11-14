"""
Состав копии (раздел 20.4 ТЗ): архив на каждый volume с данными — с тем же
именем, что ждёт `deploy/install.sh --restore` (`RESTORE_ARCHIVES` и
`RESTORE_OPTIONAL_ARCHIVES`, тест сверяет). Volume подключены к
`backup-worker` только для чтения в `<BACKUP_SOURCE_ROOT>/<имя>`.

Код и образы не копируются — их даёт `install.sh`; кеши тоже: они
восстанавливаются сами, а места занимают много.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_SOURCE_ROOT = Path("/data/backup-src")
SOURCE_ROOT_ENV = "BACKUP_SOURCE_ROOT"
# `.env` сервера: смонтирован каталог установки (`TRACKER_ENV_DIR`).
ENV_FILE_RELATIVE = Path("env/.env")
# Байт-код Python пересоздаётся при запуске — в любом компоненте.
COMMON_EXCLUDES: tuple[str, ...] = ("__pycache__", "*/__pycache__")
_CACHE_EXCLUDES: tuple[str, ...] = ("*/cache",)


@dataclass(frozen=True, slots=True)
class Component:
    # Имя volume и архива `<name>.tar.gz`.
    name: str
    # Обязательный: без него `install.sh --restore` не восстановит сервер.
    required: bool
    # Шаблоны fnmatch относительных путей каталогов, которые не копируются.
    excludes: tuple[str, ...] = ()

    @property
    def archive_name(self) -> str:
        return f"{self.name}.tar.gz"

    @property
    def all_excludes(self) -> tuple[str, ...]:
        return COMMON_EXCLUDES + self.excludes


COMPONENTS: tuple[Component, ...] = (
    # Репозитории целиком, с `.git`: незапушенные коммиты и правки агента.
    Component("task_repos", required=True),
    Component("user_files", required=True),
    Component("log_archive", required=True),
    Component("claude_sessions", required=False, excludes=_CACHE_EXCLUDES),
    # Учётки LLM-прокси с токенами OAuth.
    Component("cliproxy_data", required=False),
    # Иначе после восстановления сменится отпечаток SFTP-сервера.
    Component("sftp_host_keys", required=False),
)


def source_root() -> Path:
    return Path(os.environ.get(SOURCE_ROOT_ENV, str(DEFAULT_SOURCE_ROOT)))
