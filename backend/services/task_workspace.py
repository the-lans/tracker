"""Рабочая директория задачи: подготовка перед сессией и push по завершении.

ТЗ разделы: 1.2 (сценарии 1, 10), 3.1 (`task_repositories`, `templates`),
11.3 (слэш-команды из `.claude/commands/` шаблона), 17.4 (пуш в Git — под
распределённой блокировкой).

Структура: ``{repos_root}/{task.code}/`` — корень задачи и `cwd` сессии
Claude Code; внутри — по директории на каждый репозиторий. Файлы шаблона
(CLAUDE.md, .claude/commands/*.md, .claude/settings.json) пишутся в корень
задачи, а не внутрь git-репозиториев: Claude Code находит их из своего
`cwd`, и они не попадают в коммиты рабочих веток.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

import sqlalchemy as sa

from app_logging.config import get_logger
from db.models.enums import MergeStatus, RepositoryRole
from db.models.repositories import Repository, Template
from db.models.tasks import Task, TaskRepository
from services.distributed_lock import acquire_task_operation_lock
from services.errors import ValidationError
from services.git_ops import clone_task_repository, push_task_repository

if TYPE_CHECKING:
    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger("task_workspace")

_GIT_PUSH_LOCK_OPERATION = "git_push"
_GIT_PUSH_LOCK_TTL_SECONDS = 600
_JSON_INDENT = 2


_REPOS_ROOT_ENV_VAR = "TRACKER_REPOS_ROOT"
_DEFAULT_REPOS_ROOT = "tracker/repos"


def resolve_repos_root() -> Path:
    """Корень репозиториев задач — volume `task_repos` (раздел 20.4)."""
    return Path(os.environ.get(_REPOS_ROOT_ENV_VAR, _DEFAULT_REPOS_ROOT))


def task_root(repos_root: Path, task: Task) -> Path:
    return repos_root / task.code


def build_branch_name(task_code: str) -> str:
    """Рабочая ветка репозитория задачи — ``feature/RR-XXXXX`` (раздел 3.1)."""
    return f"feature/{task_code}"


async def load_task_repositories(
    db_session: AsyncSession,
    task_id: uuid.UUID,
) -> list[tuple[TaskRepository, Repository]]:
    stmt = (
        sa.select(TaskRepository, Repository)
        .join(Repository, Repository.id == TaskRepository.repository_id)
        .where(TaskRepository.task_id == task_id)
        .order_by(Repository.name)
    )
    return [(row[0], row[1]) for row in (await db_session.execute(stmt)).all()]


def _safe_relative_path(raw_path: str) -> PurePosixPath:
    path = PurePosixPath(raw_path)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise ValidationError(f"Недопустимый путь файла шаблона: {raw_path!r}")
    return path


def _serialize_template_file(content: object) -> str:
    if isinstance(content, str):
        return content
    return json.dumps(content, ensure_ascii=False, indent=_JSON_INDENT)


def write_template_files(root: Path, files: dict[str, object]) -> list[str]:
    """Пишет файлы шаблона в корень задачи; существующие файлы не трогает.

    Повторная подготовка (перезапуск после `failed`) не затирает то, что
    успел изменить агент. Возвращает список реально записанных путей.
    """
    written: list[str] = []
    for raw_path, content in files.items():
        relative_path = _safe_relative_path(raw_path)
        target = root / relative_path
        if target.exists():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(_serialize_template_file(content))
        written.append(str(relative_path))
    return written


async def _load_templates(
    db_session: AsyncSession,
    repositories: list[Repository],
) -> list[Template]:
    template_ids = [repo.default_template_id for repo in repositories if repo.default_template_id]
    if not template_ids:
        return []
    stmt = sa.select(Template).where(Template.id.in_(template_ids))
    templates = (await db_session.execute(stmt)).scalars().all()
    templates_by_id = {template.id: template for template in templates}
    # Порядок — как у репозиториев: при совпадении путей побеждает первый.
    return [templates_by_id[template_id] for template_id in dict.fromkeys(template_ids)]


async def prepare_task_workspace(
    db_session: AsyncSession,
    *,
    task: Task,
    repos_root: Path,
) -> Path:
    """Клонирует ещё не склонированные репозитории и раскладывает файлы шаблонов.

    Идемпотентна: уже склонированный репозиторий (есть ``.git``) повторно не
    клонируется — так перезапуск после сбоя продолжает работу в той же
    рабочей ветке. Возвращает корень задачи (`cwd` сессии).
    """
    root = task_root(repos_root, task)
    root.mkdir(parents=True, exist_ok=True)

    pairs = await load_task_repositories(db_session, task.id)
    for task_repository, repository in pairs:
        if (root / repository.name / ".git").exists():
            continue
        await clone_task_repository(
            repository=repository,
            task_repository=task_repository,
            task_code=task.code,
            repos_root=repos_root,
        )

    for template in await _load_templates(db_session, [repository for _, repository in pairs]):
        written = write_template_files(root, template.files)
        if written:
            logger.info(
                "template_files_written",
                task_id=str(task.id),
                template_id=str(template.id),
                files=written,
            )

    if task.repo_cleaned_at is not None:
        # Директория снова на месте (перезапуск после очистки) — напоминание
        # об очистке (`cleanup_stale_worktrees`) снова должно её учитывать.
        task.repo_cleaned_at = None
        await db_session.commit()

    logger.info("task_workspace_prepared", task_id=str(task.id), repositories=len(pairs))
    return root


async def push_task_workspace(
    db_session: AsyncSession,
    *,
    task: Task,
    repos_root: Path,
    redis_client: Redis,
) -> None:
    """Раздел 1.2 (сценарий 10): пушит рабочие ветки read-write репозиториев.

    Под распределённой блокировкой (раздел 17.4, правило 12 CLAUDE.md):
    повторный запуск Celery-задачи не выполнит пуш параллельно.
    """
    root = task_root(repos_root, task)
    async with acquire_task_operation_lock(
        redis_client,
        task_id=task.id,
        operation=_GIT_PUSH_LOCK_OPERATION,
        ttl_seconds=_GIT_PUSH_LOCK_TTL_SECONDS,
    ):
        for task_repository, repository in await load_task_repositories(db_session, task.id):
            if task_repository.role is not RepositoryRole.READ_WRITE:
                continue
            await push_task_repository(
                repository=repository,
                task_repository=task_repository,
                repo_dir=root / repository.name,
            )
            task_repository.pushed_at = datetime.now(UTC)
            if task_repository.merge_status is MergeStatus.NOT_PUSHED:
                task_repository.merge_status = MergeStatus.PUSHED
            await db_session.commit()
