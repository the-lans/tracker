"""Git-провижининг репозиториев задачи (этап 4 плана реализации).

ТЗ разделы: 1.2 (сценарии 1, 10), 3.1 (`task_repositories`), 14
(`rebase_conflict`), 19.3 (изоляция — здесь применимо только "монтируется
директория репозиториев текущей задачи", сетевая изоляция относится к
скрипт-нодам, раздел 11.4).

Deploy-ключ репозитория хранится в БД зашифрованным (`services/crypto`) и
никогда не попадает на диск постоянно — на время каждой git-операции он
пишется во временный файл с правами 0600 и передаётся `git` через
переменную окружения ``GIT_SSH_COMMAND``, удаляется сразу после операции.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from app_logging.config import get_logger
from db.models.enums import RepositoryRole
from db.models.repositories import Repository
from db.models.tasks import TaskRepository
from services.crypto import decrypt
from services.errors import ExternalServiceError

logger = get_logger("git_ops")

_KEY_FILE_MODE = 0o600

# Ребейз переписывает коммиты и требует committer-идентичность; в контейнере
# воркера глобального git-конфига нет. Автор коммитов при ребейзе сохраняется.
_DEFAULT_GIT_IDENTITY = {
    "GIT_COMMITTER_NAME": "AI Tracker",
    "GIT_COMMITTER_EMAIL": "tracker@localhost",
}


class RebaseConflictError(Exception):
    """Конфликт при ребейзе рабочей ветки на обновлённую базовую (раздел 14 ТЗ)."""

    def __init__(self, *, conflicting_files: list[str]) -> None:
        super().__init__(f"Конфликт ребейза: {', '.join(conflicting_files)}")
        self.conflicting_files = conflicting_files


@asynccontextmanager
async def _deploy_key_env(repository: Repository) -> AsyncIterator[dict[str, str]]:
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".key") as key_file:
        key_file.write(decrypt(repository.deploy_key_encrypted))
        key_path = Path(key_file.name)
    key_path.chmod(_KEY_FILE_MODE)
    try:
        # Окружение процесса наследуется (PATH, HOME), а не заменяется целиком.
        yield {
            **_DEFAULT_GIT_IDENTITY,
            **os.environ,
            "GIT_SSH_COMMAND": (
                f"ssh -i {key_path} -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null"
            ),
        }
    finally:
        key_path.unlink(missing_ok=True)


async def _run_git(
    *args: str,
    cwd: Path,
    env: dict[str, str],
    check: bool = True,
) -> tuple[int, str, str]:
    process = await asyncio.create_subprocess_exec(
        "git",
        *args,
        cwd=str(cwd),
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    returncode = process.returncode if process.returncode is not None else -1
    if check and returncode != 0:
        raise ExternalServiceError(
            f"git {' '.join(args)} завершился с кодом {returncode}: {stderr.decode().strip()}",
            is_transient=False,
        )
    return returncode, stdout.decode(), stderr.decode()


async def clone_task_repository(
    *,
    repository: Repository,
    task_repository: TaskRepository,
    task_code: str,
    repos_root: Path,
) -> Path:
    """Клонирует репозиторий в ``{repos_root}/{task_code}/{repository.name}/``.

    Также создаёт рабочую ветку ``task_repository.branch_name`` от
    ``task_repository.base_branch``.
    """
    target_dir = repos_root / task_code / repository.name
    target_dir.parent.mkdir(parents=True, exist_ok=True)

    async with _deploy_key_env(repository) as env:
        await _run_git(
            "clone",
            "--branch",
            task_repository.base_branch,
            repository.git_url,
            str(target_dir),
            cwd=repos_root,
            env=env,
        )
        await _run_git(
            "checkout",
            "-b",
            task_repository.branch_name,
            cwd=target_dir,
            env=env,
        )

    logger.info(
        "repository_cloned",
        repository_id=str(repository.id),
        task_code=task_code,
        branch_name=task_repository.branch_name,
        base_branch=task_repository.base_branch,
    )
    return target_dir


async def push_task_repository(
    *,
    repository: Repository,
    task_repository: TaskRepository,
    repo_dir: Path,
) -> None:
    """Пушит рабочую ветку в origin. No-op для ``role = read_only`` (раздел 3.1)."""
    if task_repository.role is not RepositoryRole.READ_WRITE:
        logger.info(
            "repository_push_skipped_read_only",
            repository_id=str(repository.id),
            branch_name=task_repository.branch_name,
        )
        return

    async with _deploy_key_env(repository) as env:
        await _run_git("push", "origin", task_repository.branch_name, cwd=repo_dir, env=env)

    logger.info(
        "repository_pushed",
        repository_id=str(repository.id),
        branch_name=task_repository.branch_name,
    )


async def rebase_onto_base_branch(
    *,
    repository: Repository,
    task_repository: TaskRepository,
    repo_dir: Path,
) -> None:
    """Ребейз рабочей ветки на обновлённую ``base_branch``.

    При конфликте ребейз откатывается (``git rebase --abort``) и поднимается
    `RebaseConflictError` — вызывающий код (оркестратор, этап 6/10) обязан
    перевести задачу в статус `rebase_conflict` (раздел 14).
    """
    async with _deploy_key_env(repository) as env:
        await _run_git("fetch", "origin", task_repository.base_branch, cwd=repo_dir, env=env)
        returncode, _stdout, stderr = await _run_git(
            "rebase",
            f"origin/{task_repository.base_branch}",
            cwd=repo_dir,
            env=env,
            check=False,
        )
        if returncode != 0:
            _, conflicting_output, _ = await _run_git(
                "diff",
                "--name-only",
                "--diff-filter=U",
                cwd=repo_dir,
                env=env,
            )
            await _run_git("rebase", "--abort", cwd=repo_dir, env=env)
            logger.warning(
                "repository_rebase_conflict",
                repository_id=str(repository.id),
                branch_name=task_repository.branch_name,
                base_branch=task_repository.base_branch,
                conflicting_files=conflicting_output.splitlines(),
                git_stderr=stderr.strip(),
            )
            raise RebaseConflictError(conflicting_files=conflicting_output.splitlines())

    logger.info(
        "repository_rebased",
        repository_id=str(repository.id),
        branch_name=task_repository.branch_name,
        base_branch=task_repository.base_branch,
    )
