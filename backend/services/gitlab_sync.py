"""Синхронизация с GitLab (раздел 16.2 ТЗ): `sync_gitlab_merge_status`,
`rebase_child_branches_on_parent_merge`.

Раздел 17.3: временный сбой GitLab API (сеть, 5xx, 408, 429) не прерывает
цикл по остальным репозиториям и повторяется на следующем запуске;
постоянный сбой репозитория (прочие 4xx) пишется в `app_logs`, автор задачи
получает уведомление, а репозиторий пропускается на
`PERMANENT_FAILURE_COOLDOWN_SECONDS` — без бесполезных повторов и повторных
уведомлений. Отклонённый токен (401/403) — сбой всей интеграции: цикл
прерывается, ошибка пишется в `app_logs` один раз для администратора, и
синхронизация ставится на ту же паузу целиком. После паузы — новая попытка:
администратор мог исправить токен или путь проекта.

`closed` (MR закрыт без слияния) намеренно не отображается ни в одно из
значений `task_repositories.merge_status` (`not_pushed`/`pushed`/`merged`/
`conflict`) — схема раздела 3.1 не выделяет под это состояние отдельного
значения (`conflict` описывает конфликт push/rebase, не отклонённый MR);
`sync_task_repository_merge_status` в этом случае осознанно не меняет
статус, а не выбирает ближайшее по смыслу неверное значение.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import sqlalchemy as sa

from app_logging.config import get_logger
from clients.gitlab import GitlabAccessDeniedError, project_path_from_git_url
from db.models.enums import AppLogLevel, MergeStatus, TaskStatus
from db.models.logs import AppLog
from db.models.repositories import Repository
from db.models.tasks import Task, TaskRepository
from services.errors import ConflictError, ExternalServiceError
from services.git_ops import RebaseConflictError, rebase_onto_base_branch
from services.notifications import NotificationEvent, notify_task_event
from services.task_status import transition_task_status

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncSession

    from clients.gitlab import GitlabClient

logger = get_logger("gitlab_sync")

PERMANENT_FAILURE_COOLDOWN_SECONDS = 24 * 60 * 60
_SYNC_LOG_SOURCE = "periodic.sync_gitlab_merge_status"

_GITLAB_STATE_TO_MERGE_STATUS: dict[str, MergeStatus] = {
    "merged": MergeStatus.MERGED,
}


async def sync_task_repository_merge_status(
    db_session: AsyncSession,
    *,
    task_repository: TaskRepository,
    repository: Repository,
    gitlab_client: GitlabClient,
) -> MergeStatus | None:
    """Раздел 16.2: обновляет `merge_status` по данным GitLab API.

    Возвращает новый статус, если он изменился, иначе `None`.
    """
    if task_repository.merge_status is MergeStatus.NOT_PUSHED:
        return None  # ещё не запушено — GitLab не видит эту ветку

    project_path = project_path_from_git_url(repository.git_url)
    state = await gitlab_client.get_latest_merge_request_state(
        project_path=project_path,
        source_branch=task_repository.branch_name,
    )
    if state is None:
        return None

    new_status = _GITLAB_STATE_TO_MERGE_STATUS.get(state)
    if new_status is None or new_status == task_repository.merge_status:
        return None

    task_repository.merge_status = new_status
    await db_session.commit()
    logger.info(
        "task_repository_merge_status_synced",
        task_repository_id=str(task_repository.id),
        new_status=new_status,
    )
    return new_status


ACCESS_DENIED_KEY = "gitlab-sync:access-denied"


def permanent_failure_key(task_repository_id: uuid.UUID) -> str:
    return f"gitlab-sync:permanent:{task_repository_id}"


async def _report_access_denied(
    db_session: AsyncSession,
    *,
    redis_client: Redis,
    error: GitlabAccessDeniedError,
) -> None:
    """Токен один на систему — сообщается администратору, а не авторам задач."""
    logger.error("gitlab_sync_access_denied", error=error.message)
    # SET NX: запись одна за паузу, даже если два запуска пересеклись (правило 12).
    first_report = await redis_client.set(
        ACCESS_DENIED_KEY,
        "1",
        nx=True,
        ex=PERMANENT_FAILURE_COOLDOWN_SECONDS,
    )
    if first_report:
        db_session.add(
            AppLog(
                level=AppLogLevel.ERROR,
                source=_SYNC_LOG_SOURCE,
                message=(
                    f"{error.message}: синхронизация статусов MR приостановлена на сутки. "
                    "Проверьте токен GitLab в «Системных настройках»"
                ),
                context={},
            ),
        )
        await db_session.commit()


async def _report_permanent_failure(
    db_session: AsyncSession,
    *,
    task: Task,
    task_repository: TaskRepository,
    error: ExternalServiceError,
) -> None:
    db_session.add(
        AppLog(
            level=AppLogLevel.ERROR,
            source=_SYNC_LOG_SOURCE,
            message=f"Постоянный сбой GitLab API: {error.message}",
            context={"task_repository_id": str(task_repository.id)},
            task_id=task.id,
        ),
    )
    await db_session.commit()
    await notify_task_event(
        db_session,
        event=NotificationEvent.GITLAB_SYNC_FAILED,
        task=task,
        detail=f"{task.code}: {error.message}",
    )


async def sync_merge_statuses(
    db_session: AsyncSession,
    *,
    rows: Sequence[tuple[TaskRepository, Repository, Task]],
    gitlab_client: GitlabClient,
    redis_client: Redis,
) -> None:
    """Раздел 16.2 + 17.3: `sync_gitlab_merge_status` по всем репозиториям задач."""
    if await redis_client.exists(ACCESS_DENIED_KEY):
        logger.info("gitlab_sync_paused_access_denied")
        return
    for task_repository, repository, task in rows:
        key = permanent_failure_key(task_repository.id)
        if await redis_client.exists(key):
            continue
        try:
            await sync_task_repository_merge_status(
                db_session,
                task_repository=task_repository,
                repository=repository,
                gitlab_client=gitlab_client,
            )
        except GitlabAccessDeniedError as exc:
            await _report_access_denied(db_session, redis_client=redis_client, error=exc)
            return
        except ExternalServiceError as exc:
            # Ошибка — ответ GitLab до каких-либо изменений в БД: откатывать нечего.
            if exc.is_transient:
                logger.warning(
                    "gitlab_sync_transient_failure",
                    task_repository_id=str(task_repository.id),
                    error=exc.message,
                )
                continue
            logger.error(
                "gitlab_sync_permanent_failure",
                task_repository_id=str(task_repository.id),
                error=exc.message,
            )
            # SET NX: уведомление уходит один раз за паузу, даже если два
            # запуска задачи пересеклись (правило 12 CLAUDE.md).
            if await redis_client.set(key, "1", nx=True, ex=PERMANENT_FAILURE_COOLDOWN_SECONDS):
                await _report_permanent_failure(
                    db_session,
                    task=task,
                    task_repository=task_repository,
                    error=exc,
                )


# Задачи с живой сессией: только у них конфликт разрешит агент (раздел 14).
_REBASABLE_STATUSES = frozenset(
    {
        TaskStatus.IN_PROGRESS,
        TaskStatus.PAUSED,
        TaskStatus.PLAN_REVIEW,
        TaskStatus.AWAITING_INPUT,
    },
)
# Из ожидания решения задача в `rebase_conflict` не переходит (раздел 14.1):
# конфликт остаётся признаком в `task_repositories`, и воркер разберёт его в
# ближайшей точке проверки, когда решение будет принято.
_CONFLICT_STATUS_SOURCES = frozenset({TaskStatus.IN_PROGRESS, TaskStatus.PAUSED})


async def rebase_child_task_repositories_on_parent_merge(
    db_session: AsyncSession,
    *,
    parent_task_repository: TaskRepository,
    repos_root: Path,
) -> list[uuid.UUID]:
    """Раздел 16.2: при смердже родительской ветки — ребейз дочерних задач.

    "Дочерняя" — задача, чей `parent_task_id` указывает на родителя этой
    ветки, с `task_repositories.base_branch`, совпадающим со смерженной
    веткой родителя того же репозитория. Смердж переносит содержимое ветки
    родителя в ЕГО базовую ветку (например, `main`) — ветка родителя после
    этого может быть даже удалена (типичная практика GitLab). Поэтому
    дочерняя задача переключает свою базовую ветку на базовую ветку
    родителя (а не продолжает ссылаться на смерженную ветку) и ребейзится
    уже на неё.
    """
    if parent_task_repository.merge_status is not MergeStatus.MERGED:
        return []

    stmt = (
        sa.select(TaskRepository, Repository, Task)
        .join(Task, Task.id == TaskRepository.task_id)
        .join(Repository, Repository.id == TaskRepository.repository_id)
        .where(
            Task.parent_task_id == parent_task_repository.task_id,
            TaskRepository.repository_id == parent_task_repository.repository_id,
            TaskRepository.base_branch == parent_task_repository.branch_name,
        )
    )
    rows = (await db_session.execute(stmt)).all()

    rebased_task_ids: list[uuid.UUID] = []
    for child_task_repository, repository, child_task in rows:
        child_task_repository.base_branch = parent_task_repository.base_branch
        await db_session.commit()
        if child_task.status not in _REBASABLE_STATUSES:
            # Решение 2026-10-19: завершённые задачи не ребейзятся (их ветка
            # уже запушена), а ещё не начатые склонируют свежую базу сами.
            logger.info(
                "child_task_rebase_skipped",
                task_id=str(child_task.id),
                repository_id=str(repository.id),
                status=child_task.status,
            )
            continue
        repo_dir = repos_root / child_task.code / repository.name
        try:
            await rebase_onto_base_branch(
                repository=repository,
                task_repository=child_task_repository,
                repo_dir=repo_dir,
            )
            rebased_task_ids.append(child_task.id)
            logger.info(
                "child_task_repository_rebased",
                task_id=str(child_task.id),
                repository_id=str(repository.id),
            )
        except RebaseConflictError:
            # Признак в БД переживает и смену статуса воркером, и уход
            # задачи в `failed` — его проверяет `services/rebase_resolution.py`.
            child_task_repository.merge_status = MergeStatus.CONFLICT
            await db_session.commit()
            logger.warning(
                "child_task_rebase_conflict",
                task_id=str(child_task.id),
                repository_id=str(repository.id),
            )
            if child_task.status not in _CONFLICT_STATUS_SOURCES:
                continue
            try:
                await transition_task_status(
                    db_session,
                    task_id=child_task.id,
                    from_status=child_task.status,
                    to_status=TaskStatus.REBASE_CONFLICT,
                )
            except ConflictError:
                # Воркер успел сменить статус (пауза, продолжение) — конфликт
                # он разберёт по признаку в ближайшей точке проверки.
                logger.info("child_task_rebase_conflict_status_changed", task_id=str(child_task.id))
    return rebased_task_ids
