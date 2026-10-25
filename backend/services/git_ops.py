"""Git-провижининг репозиториев задачи (этап 4 плана реализации).

ТЗ разделы: 1.2 (сценарии 1, 10), 3.1 (`task_repositories`), 14
(`rebase_conflict`), 19.3 (изоляция — здесь применимо только "монтируется
директория репозиториев текущей задачи", сетевая изоляция относится к
скрипт-нодам, раздел 11.4).

Deploy-ключ репозитория хранится в БД зашифрованным (`services/crypto`) и
никогда не попадает на диск постоянно — на время каждой git-операции он
пишется во временный файл с правами 0600 и передаётся `git` через
переменную окружения ``GIT_SSH_COMMAND``, удаляется сразу после операции.

Рабочую директорию меняют агент и script-ноды, поэтому git воркера не
исполняет ничего из репозитория (раздел 19.3, решение №22 плана): хуки и
`fsmonitor` отключены параметрами командной строки, системный и глобальный
конфиг не читаются, а локальный `.git/config` перед каждой операцией
сводится к белому списку ключей с `origin` из `repositories.git_url`.
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
from services.task_codes import validate_task_code

logger = get_logger("git_ops")

_HEAD_REF_PREFIX = "refs/heads/"

_KEY_FILE_MODE = 0o600

# Ребейз переписывает коммиты и требует committer-идентичность; в контейнере
# воркера глобального git-конфига нет. Автор коммитов при ребейзе сохраняется.
_DEFAULT_GIT_IDENTITY = {
    "GIT_COMMITTER_NAME": "AI Tracker",
    "GIT_COMMITTER_EMAIL": "tracker@localhost",
}
# Системный и глобальный конфиг не читаются, git ничего не спрашивает.
_ISOLATED_GIT_ENV = {
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_TERMINAL_PROMPT": "0",
}
# Параметры командной строки сильнее локального конфига: даже если его
# успели изменить после очистки, хуки и `fsmonitor` не запустятся.
_HARDENING_ARGS = (
    "-c",
    f"core.hooksPath={os.devnull}",
    "-c",
    "core.fsmonitor=false",
    "-c",
    "protocol.ext.allow=never",
)
# Ключи локального конфига, без которых репозиторий и рабочая ветка не
# работают; всё остальное (фильтры, `include`, `gpg.program`,
# `core.sshCommand`, `url.*.insteadOf` и т. п.) удаляется.
_LOCAL_CONFIG_ALLOWED_KEYS = frozenset(
    {
        "core.repositoryformatversion",
        "core.filemode",
        "core.bare",
        "core.logallrefupdates",
        "core.ignorecase",
        "core.precomposeunicode",
        "core.symlinks",
    },
)
_LOCAL_CONFIG_ALLOWED_PREFIXES = ("extensions.",)
_BRANCH_SECTION = "branch."
_BRANCH_ALLOWED_SUFFIXES = (".remote", ".merge")
_ORIGIN_URL_KEY = "remote.origin.url"
_ORIGIN_FETCH_KEY = "remote.origin.fetch"
_ORIGIN_FETCH_REFSPEC = "+refs/heads/*:refs/remotes/origin/*"


_REBASE_STATE_DIRS = ("rebase-merge", "rebase-apply")


def _rebase_in_progress(repo_dir: Path) -> bool:
    git_dir = repo_dir / ".git"
    return any((git_dir / state_dir).exists() for state_dir in _REBASE_STATE_DIRS)


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
            **_ISOLATED_GIT_ENV,
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
        *_HARDENING_ARGS,
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


def _is_allowed_local_key(key: str) -> bool:
    if key in _LOCAL_CONFIG_ALLOWED_KEYS or key.startswith(_LOCAL_CONFIG_ALLOWED_PREFIXES):
        return True
    return key.startswith(_BRANCH_SECTION) and key.endswith(_BRANCH_ALLOWED_SUFFIXES)


ConfigEntry = tuple[str, str]


def _parse_config_entries(listing: str) -> list[ConfigEntry]:
    """Вывод ``git config --list -z``: записи ``ключ\\nзначение`` через NUL."""
    entries = []
    for record in listing.split("\0"):
        if record:
            key, _, value = record.partition("\n")
            entries.append((key, value))
    return entries


async def _read_config_file(
    path: Path, *, repo_dir: Path, env: dict[str, str]
) -> list[ConfigEntry]:
    _, listing, _ = await _run_git(
        "config",
        "--file",
        str(path),
        "--no-includes",
        "--list",
        "-z",
        cwd=repo_dir,
        env=env,
    )
    return _parse_config_entries(listing)


async def _write_config_file(
    path: Path,
    entries: list[ConfigEntry],
    *,
    repo_dir: Path,
    env: dict[str, str],
) -> None:
    path.unlink(missing_ok=True)
    for key, value in entries:
        await _run_git("config", "--file", str(path), "--add", key, value, cwd=repo_dir, env=env)


async def sanitize_local_config(*, repo_dir: Path, git_url: str, env: dict[str, str]) -> None:
    """
    Пересобирает `.git/config` из белого списка ключей; `origin` — адрес из
    `repositories.git_url` и стандартный refspec (раздел 19.3). Новый файл
    подменяет старый целиком.
    """
    config_path = repo_dir / ".git" / "config"
    entries = await _read_config_file(config_path, repo_dir=repo_dir, env=env)
    allowed = [(key, value) for key, value in entries if _is_allowed_local_key(key)]
    origin = [(_ORIGIN_URL_KEY, git_url), (_ORIGIN_FETCH_KEY, _ORIGIN_FETCH_REFSPEC)]

    clean_path = config_path.with_name("config.tracker-clean")
    await _write_config_file(clean_path, [*allowed, *origin], repo_dir=repo_dir, env=env)
    clean_path.replace(config_path)

    kept_keys = {key for key, _ in [*allowed, *origin]}
    dropped = sorted({key for key, _ in entries} - kept_keys)
    if dropped:
        logger.warning("git_local_config_sanitized", repo_dir=str(repo_dir), dropped_keys=dropped)


@asynccontextmanager
async def _existing_repository_env(
    repository: Repository,
    repo_dir: Path,
) -> AsyncIterator[dict[str, str]]:
    """Окружение git с deploy-ключом для уже клонированного репозитория — после очистки конфига."""
    async with _deploy_key_env(repository) as env:
        await sanitize_local_config(repo_dir=repo_dir, git_url=repository.git_url, env=env)
        yield env


async def _remote_branch_exists(branch_name: str, *, repo_dir: Path, env: dict[str, str]) -> bool:
    _, remote_heads, _ = await _run_git(
        "ls-remote",
        "--heads",
        "origin",
        branch_name,
        cwd=repo_dir,
        env=env,
    )
    # `ls-remote` сравнивает шаблон с концом имени ссылки: без точной
    # проверки `archive/feature/RR-1` сошла бы за `feature/RR-1`.
    branch_ref = f"{_HEAD_REF_PREFIX}{branch_name}"
    return any(line.split("\t")[-1] == branch_ref for line in remote_heads.splitlines())


async def _checkout_work_branch(branch_name: str, *, repo_dir: Path, env: dict[str, str]) -> None:
    """
    Рабочая ветка из origin, если она уже запушена, иначе — новая от базовой.
    """
    if await _remote_branch_exists(branch_name, repo_dir=repo_dir, env=env):
        await _run_git("fetch", "origin", f"{branch_name}:{branch_name}", cwd=repo_dir, env=env)
        await _run_git("checkout", branch_name, cwd=repo_dir, env=env)
    else:
        await _run_git("checkout", "-b", branch_name, cwd=repo_dir, env=env)


async def clone_task_repository(
    *,
    repository: Repository,
    task_repository: TaskRepository,
    task_code: str,
    repos_root: Path,
) -> Path:
    """Клонирует репозиторий в ``{repos_root}/{task_code}/{repository.name}/``.

    Рабочая ветка ``task_repository.branch_name`` создаётся от
    ``task_repository.base_branch`` — либо берётся из origin, если она там
    уже есть: перезапуск после ручной очистки директории (раздел 14.3) не
    должен терять запушенную работу.
    """
    target_dir = repos_root / validate_task_code(task_code) / repository.name
    target_dir.parent.mkdir(parents=True, exist_ok=True)

    async with _deploy_key_env(repository) as env:
        await _run_git(
            "clone",
            "--branch",
            task_repository.base_branch,
            # Адрес и каталог — только позиционные аргументы, не опции git.
            "--",
            repository.git_url,
            str(target_dir),
            cwd=repos_root,
            env=env,
        )
        await _checkout_work_branch(task_repository.branch_name, repo_dir=target_dir, env=env)

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

    async with _existing_repository_env(repository, repo_dir) as env:
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
    async with _existing_repository_env(repository, repo_dir) as env:
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
            # Ребейз мог и не начаться (например, на грязном дереве) — тогда
            # отменять нечего, а `--abort` сам завершился бы ошибкой.
            if _rebase_in_progress(repo_dir):
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


async def has_uncommitted_changes(*, repository: Repository, repo_dir: Path) -> bool:
    """Незакоммиченные или неотслеживаемые изменения рабочей директории."""
    async with _existing_repository_env(repository, repo_dir) as env:
        _, status, _ = await _run_git("status", "--porcelain", cwd=repo_dir, env=env)
    return bool(status.strip())


async def is_rebased_onto_base(
    *,
    repository: Repository,
    task_repository: TaskRepository,
    repo_dir: Path,
) -> bool:
    """Проверка результата автообработки `rebase_conflict` (раздел 14):
    ребейз завершён и рабочая ветка уже содержит актуальную ``base_branch``.
    """
    if _rebase_in_progress(repo_dir):
        return False
    async with _existing_repository_env(repository, repo_dir) as env:
        await _run_git("fetch", "origin", task_repository.base_branch, cwd=repo_dir, env=env)
        returncode, _stdout, _stderr = await _run_git(
            "merge-base",
            "--is-ancestor",
            f"origin/{task_repository.base_branch}",
            "HEAD",
            cwd=repo_dir,
            env=env,
            check=False,
        )
    return returncode == 0
