"""
Перенос истории сессий из каталогов прежних LLM-аккаунтов (раздел 20.6 ТЗ).

До LLM-прокси сессия задачи жила в `CLAUDE_CONFIG_DIR` её аккаунта
(`llm_accounts.claude_config_dir` внутри `CLAUDE_ACCOUNTS_ROOT`) рядом с
файлами входа. Теперь история хранится у задачи (раздел 6.4): переносится
только сама история сессии — `projects/<проект>/<session_id>.jsonl` и
каталог `projects/<проект>/<session_id>/`, — входы (`.credentials.json`) не
копируются. Уже перенесённые файлы не перезаписываются: повторный запуск
ничего не меняет, а продолженная после переноса сессия не откатывается.
"""

from __future__ import annotations

import os
import shutil
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import sqlalchemy as sa

from app_logging.config import get_logger
from db.models.llm import LlmAccount
from db.models.tasks import Task
from services.claude_config import session_config_dir

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger("session_history_migration")

ACCOUNTS_ROOT_ENV_VAR = "CLAUDE_ACCOUNTS_ROOT"
# Volume `claude_accounts` контейнера backend (docker-compose.yml).
DEFAULT_ACCOUNTS_ROOT = "/data/claude-accounts"
_PROJECTS_DIR = "projects"
_HISTORY_SUFFIX = ".jsonl"


@dataclass(slots=True)
class HistoryMigrationResult:
    migrated_tasks: list[str] = field(default_factory=list)
    copied_files: int = 0
    # Задачи, историю которых перенести нельзя: каталога нет или он вне корня.
    skipped_tasks: list[str] = field(default_factory=list)


def resolve_accounts_root() -> Path:
    return Path(os.environ.get(ACCOUNTS_ROOT_ENV_VAR, DEFAULT_ACCOUNTS_ROOT))


async def _tasks_with_account_history(
    db_session: AsyncSession,
) -> list[tuple[str, str, str]]:
    stmt = (
        sa.select(Task.code, Task.session_id, LlmAccount.claude_config_dir)
        .join(LlmAccount, LlmAccount.id == Task.llm_account_id)
        .where(Task.session_id.is_not(None), LlmAccount.claude_config_dir.is_not(None))
        .order_by(Task.code)
    )
    return [
        (code, str(session_id), str(config_dir))
        for code, session_id, config_dir in (await db_session.execute(stmt)).all()
    ]


def _inside(path: Path, root: Path) -> bool:
    return path.resolve().is_relative_to(root.resolve())


def _copy_missing_file(source: Path, target: Path) -> int:
    # Ссылки не переносятся: они могли бы указывать за пределы каталога аккаунта.
    if source.is_symlink() or not source.is_file() or target.exists():
        return 0
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return 1


def _copy_missing_tree(source: Path, target: Path) -> int:
    copied = 0
    for directory, _subdirs, files in os.walk(source):
        relative = Path(directory).relative_to(source)
        for name in files:
            copied += _copy_missing_file(Path(directory) / name, target / relative / name)
    return copied


def _copy_session_history(projects: Path, target_projects: Path, session_id: str) -> int:
    copied = 0
    for project in sorted(projects.iterdir()):
        if project.is_symlink() or not project.is_dir():
            continue
        target = target_projects / project.name
        copied += _copy_missing_file(
            project / f"{session_id}{_HISTORY_SUFFIX}",
            target / f"{session_id}{_HISTORY_SUFFIX}",
        )
        session_dir = project / session_id
        if session_dir.is_dir() and not session_dir.is_symlink():
            copied += _copy_missing_tree(session_dir, target / session_id)
    return copied


def _valid_session_id(session_id: str) -> bool:
    # `session_id` становится частью пути: допустим только UUID, как его выдаёт CLI.
    try:
        return str(uuid.UUID(session_id)) == session_id
    except ValueError:
        return False


async def migrate_session_histories(
    db_session: AsyncSession,
    *,
    accounts_root: Path,
) -> HistoryMigrationResult:
    result = HistoryMigrationResult()
    for code, session_id, config_dir in await _tasks_with_account_history(db_session):
        projects = Path(config_dir) / _PROJECTS_DIR
        if (
            not _valid_session_id(session_id)
            or not _inside(Path(config_dir), accounts_root)
            or not projects.is_dir()
        ):
            logger.warning("session_history_not_migrated", task_code=code)
            result.skipped_tasks.append(code)
            continue
        target_projects = session_config_dir(code) / _PROJECTS_DIR
        copied = _copy_session_history(projects, target_projects, session_id)
        result.copied_files += copied
        if copied:
            result.migrated_tasks.append(code)
    logger.info(
        "session_histories_migrated",
        tasks=len(result.migrated_tasks),
        files=result.copied_files,
        skipped=len(result.skipped_tasks),
    )
    return result
