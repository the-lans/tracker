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

from app_logging.app_logs import write_app_log
from app_logging.config import get_logger
from db.models.enums import AppLogLevel, MergeStatus, RepositoryRole
from db.models.repositories import Repository, Template
from db.models.tasks import Task, TaskRepository
from prompts.agent import (
    ADDED_REPOSITORIES_HEADER,
    ADDED_REPOSITORY_LINE,
    ADDED_REPOSITORY_READ_ONLY,
    ADDED_REPOSITORY_READ_WRITE,
)
from services.distributed_lock import acquire_task_operation_lock
from services.errors import ExternalServiceError, ValidationError
from services.git_ops import clone_task_repository, push_task_repository
from services.task_codes import validate_task_code

if TYPE_CHECKING:
    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger("task_workspace")

_GIT_PUSH_LOCK_OPERATION = "git_push"
_GIT_PUSH_LOCK_TTL_SECONDS = 600
_JSON_INDENT = 2
_CLONE_LOG_SOURCE = "task_workspace"
# Роль репозитория в служебном сообщении агенту (раздел 3.2).
_ROLE_NOTICE = {
    RepositoryRole.READ_ONLY: ADDED_REPOSITORY_READ_ONLY,
    RepositoryRole.READ_WRITE: ADDED_REPOSITORY_READ_WRITE,
}


_REPOS_ROOT_ENV_VAR = "TRACKER_REPOS_ROOT"
_DEFAULT_REPOS_ROOT = "tracker/repos"


def resolve_repos_root() -> Path:
    """Корень репозиториев задач — volume `task_repos` (раздел 20.4)."""
    return Path(os.environ.get(_REPOS_ROOT_ENV_VAR, _DEFAULT_REPOS_ROOT))


def task_root(repos_root: Path, task: Task) -> Path:
    """Каталог задачи — прямой потомок корня: код проверяется и здесь (раздел 3.1)."""
    return repos_root / validate_task_code(task.code)


def task_repos_path(task: Task) -> str:
    """
    `{{task.repos_path}}` (раздел 5): абсолютный путь директории репозиториев
    задачи на сервере — та же директория, с которой работают git и
    script-ноды, с завершающим "/".
    """
    return f"{task_root(resolve_repos_root(), task).resolve()}/"


def build_branch_name(task_code: str) -> str:
    """Рабочая ветка репозитория задачи — ``feature/RR-XXXXX`` (раздел 3.1)."""
    return f"feature/{task_code}"


async def load_task_repositories(
    db_session: AsyncSession,
    task_id: uuid.UUID,
) -> list[tuple[TaskRepository, Repository]]:
    # Флаг ребейза и статус слияния пишут периодические задачи в своих
    # сессиях БД; без перечитывания долгоживущая сессия воркера (`expire_on_commit`
    # выключен) видела бы значения на момент первой загрузки.
    stmt = (
        sa.select(TaskRepository, Repository)
        .join(Repository, Repository.id == TaskRepository.repository_id)
        .where(TaskRepository.task_id == task_id)
        .order_by(Repository.name)
        .execution_options(populate_existing=True)
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


async def clone_missing_repositories(
    db_session: AsyncSession,
    *,
    task: Task,
    repos_root: Path,
    tolerate_errors: bool = False,
) -> list[tuple[TaskRepository, Repository]]:
    """
    Клонирует репозитории задачи, которых ещё нет в её каталоге, отмечает
    `cloned_at` и раскладывает файлы их шаблонов (существующие не трогает).

    Вызывается перед прогоном и между нодами: репозиторий можно добавить к
    задаче и во время работы (раздел 3.2). Возвращает склонированные впервые —
    повторный клон после очистки каталога (раздел 14.3) новым не считается.
    ``tolerate_errors`` — между нодами: сбой клона пишется в журнал, прогон
    идёт дальше, а клон повторится в следующей точке.
    """
    root = task_root(repos_root, task)
    root.mkdir(parents=True, exist_ok=True)
    cloned: list[tuple[TaskRepository, Repository]] = []
    first_cloned: list[tuple[TaskRepository, Repository]] = []
    for task_repository, repository in await load_task_repositories(db_session, task.id):
        if (root / repository.name / ".git").exists():
            continue
        try:
            await clone_task_repository(
                repository=repository,
                task_repository=task_repository,
                task_code=task.code,
                repos_root=repos_root,
            )
        except ExternalServiceError as exc:
            if not tolerate_errors:
                raise
            await _log_clone_failure(task=task, repository=repository, error=exc)
            continue
        cloned.append((task_repository, repository))
        if task_repository.cloned_at is None:
            task_repository.cloned_at = datetime.now(UTC)
            await db_session.commit()
            first_cloned.append((task_repository, repository))
    await _write_templates(
        db_session,
        task=task,
        root=root,
        repositories=[repo for _, repo in cloned],
    )
    return first_cloned


async def _log_clone_failure(
    *,
    task: Task,
    repository: Repository,
    error: ExternalServiceError,
) -> None:
    logger.warning(
        "repository_clone_failed",
        task_id=str(task.id),
        repository_id=str(repository.id),
        error=str(error),
    )
    await write_app_log(
        level=AppLogLevel.ERROR,
        source=_CLONE_LOG_SOURCE,
        message=f"Не удалось склонировать добавленный репозиторий {repository.name}: {error}",
        context={"repository_id": str(repository.id)},
        task_id=task.id,
    )


async def _write_templates(
    db_session: AsyncSession,
    *,
    task: Task,
    root: Path,
    repositories: list[Repository],
) -> None:
    for template in await _load_templates(db_session, repositories):
        written = write_template_files(root, template.files)
        if written:
            logger.info(
                "template_files_written",
                task_id=str(task.id),
                template_id=str(template.id),
                files=written,
            )


def added_repositories_notice(
    root: Path,
    cloned: list[tuple[TaskRepository, Repository]],
) -> str | None:
    """Служебная строка для агента о репозиториях, добавленных по ходу задачи."""
    if not cloned:
        return None
    lines = [
        ADDED_REPOSITORY_LINE.format(
            name=repository.name,
            role=_ROLE_NOTICE[task_repository.role],
            path=root / repository.name,
        )
        for task_repository, repository in cloned
    ]
    return "\n".join([ADDED_REPOSITORIES_HEADER, *lines])


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
    await clone_missing_repositories(db_session, task=task, repos_root=repos_root)
    pairs = await load_task_repositories(db_session, task.id)
    await _write_templates(
        db_session,
        task=task,
        root=root,
        repositories=[repo for _, repo in pairs],
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
