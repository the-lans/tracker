"""
Общее у бэкапа и проверки восстановления (раздел 20.4 ТЗ): одна блокировка
на двоих, история запусков в `backup_runs` и уведомление администраторов о
сбое (раздел 18.2).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import sqlalchemy as sa

from app_logging.config import get_logger
from db.models.backups import BackupRun
from db.models.enums import BackupRunKind, BackupRunStatus, UserRole
from db.models.users import User
from services.backup.bundle import BundleError
from services.backup.crypto_gpg import GpgError
from services.backup.dump import DumpError
from services.backup.storage import StorageError
from services.distributed_lock import wait_for_lock
from services.notifications import NotificationEvent, notify_user_event

if TYPE_CHECKING:
    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger("backup_runs")

BACKUP_LOCK_KEY = "backup:lock"
# Дольше самого долгого бэкапа: истёкшая блокировка пустила бы второй.
BACKUP_LOCK_TTL_SECONDS = 6 * 60 * 60
# Бэкап в 03:00 МСК ждёт проверку, начатую в 02:00 в воскресенье.
BACKUP_LOCK_WAIT_SECONDS = 3 * 60 * 60
_LOCK_POLL_SECONDS = 15.0
RUNS_KEPT_PER_KIND = 100
INTERRUPTED_MESSAGE = "Запуск прерван: воркер бэкапа перезапустился до завершения"


class BackupError(Exception):
    """Бэкап или проверка не удались; текст — для администратора, без секретов."""


@asynccontextmanager
async def backup_lock(
    redis_client: Redis,
    *,
    wait_seconds: float = BACKUP_LOCK_WAIT_SECONDS,
    poll_seconds: float = _LOCK_POLL_SECONDS,
) -> AsyncIterator[None]:
    """Бэкап и проверка не идут одновременно: оба читают и пишут staging и S3."""
    async with wait_for_lock(
        redis_client,
        BACKUP_LOCK_KEY,
        ttl_seconds=BACKUP_LOCK_TTL_SECONDS,
        wait_seconds=wait_seconds,
        poll_seconds=poll_seconds,
    ) as acquired:
        if not acquired:
            raise BackupError("Предыдущий бэкап или проверка ещё не закончились")
        yield


async def close_interrupted_runs(db_session: AsyncSession, *, current: BackupRun) -> int:
    """
    Под блокировкой бэкапа другой запуск идти не может: `running` у записей,
    начатых раньше этой, — след процесса, убитого посреди работы (перезапуск
    воркера при обновлении сервера). Без этого карточка показывала бы его
    выполняющимся. Начатые позже ещё ждут блокировку — их не трогаем.
    """
    result = await db_session.execute(
        sa.update(BackupRun)
        .where(
            BackupRun.status == BackupRunStatus.RUNNING,
            BackupRun.started_at
            < sa.select(BackupRun.started_at).where(BackupRun.id == current.id).scalar_subquery(),
        )
        .values(
            status=BackupRunStatus.FAILED,
            finished_at=datetime.now(UTC),
            error_message=INTERRUPTED_MESSAGE,
        )
        .execution_options(synchronize_session=False),
    )
    await db_session.commit()
    closed = int(result.rowcount or 0)  # type: ignore[attr-defined]
    if closed:
        logger.warning("backup_interrupted_runs_closed", count=closed)
    return closed


async def start_run(db_session: AsyncSession, *, kind: BackupRunKind) -> BackupRun:
    run = BackupRun(id=uuid.uuid4(), kind=kind, status=BackupRunStatus.RUNNING)
    db_session.add(run)
    await db_session.commit()
    return run


async def finish_run(
    db_session: AsyncSession,
    run: BackupRun,
    *,
    status: BackupRunStatus,
    error_message: str | None = None,
    **fields: Any,
) -> bool:
    """
    Итог запуска; только из `running` (compare-and-swap) — повторное
    завершение ничего не меняет. `True` — итог записан этим вызовом.
    """
    values: dict[str, Any] = {
        "status": status,
        "finished_at": datetime.now(UTC),
        "error_message": error_message,
        **fields,
    }
    result = await db_session.execute(
        sa.update(BackupRun)
        .where(BackupRun.id == run.id, BackupRun.status == BackupRunStatus.RUNNING)
        .values(**values)
        .execution_options(synchronize_session=False),
    )
    await db_session.commit()
    finished = bool(result.rowcount == 1)  # type: ignore[attr-defined]
    if not finished:
        logger.warning("backup_run_already_finished", run_id=str(run.id))
    await trim_runs(db_session, kind=run.kind)
    await db_session.refresh(run)
    return finished


async def trim_runs(db_session: AsyncSession, *, kind: BackupRunKind) -> None:
    kept = (
        sa.select(BackupRun.id)
        .where(BackupRun.kind == kind)
        .order_by(BackupRun.started_at.desc())
        .limit(RUNS_KEPT_PER_KIND)
    )
    await db_session.execute(
        sa.delete(BackupRun).where(BackupRun.kind == kind, BackupRun.id.not_in(kept)),
    )
    await db_session.commit()


async def latest_run(db_session: AsyncSession, *, kind: BackupRunKind) -> BackupRun | None:
    run: BackupRun | None = await db_session.scalar(
        sa.select(BackupRun)
        .where(BackupRun.kind == kind)
        .order_by(BackupRun.started_at.desc())
        .limit(1),
    )
    return run


async def notify_admins(db_session: AsyncSession, *, event: NotificationEvent, detail: str) -> None:
    admin_ids = (
        await db_session.scalars(
            sa.select(User.id).where(
                User.role == UserRole.ADMIN,
                User.is_active == True,  # noqa: E712
            ),
        )
    ).all()
    for admin_id in admin_ids:
        await notify_user_event(db_session, event=event, user_id=admin_id, detail=detail)


def failure_message(exc: BaseException) -> str:
    """
    Текст сбоя для администратора. Ожидаемые ошибки бэкапа сами объясняют
    причину без секретов; у прочих — только тип: текст произвольного
    исключения может содержать параметры подключения.
    """
    if isinstance(exc, BackupError | BundleError | DumpError | GpgError | StorageError):
        return str(exc) or type(exc).__name__
    if isinstance(exc, OSError):
        return f"Ошибка файловой системы: {exc.strerror or type(exc).__name__}"
    return f"Внутренняя ошибка: {type(exc).__name__}"


async def fail_run(
    db_session: AsyncSession,
    run: BackupRun,
    *,
    message: str,
    event: NotificationEvent,
) -> None:
    """Запуск — `failed`; уведомление только тому вызову, который записал итог."""
    await db_session.rollback()
    if await finish_run(db_session, run, status=BackupRunStatus.FAILED, error_message=message):
        await notify_admins(db_session, event=event, detail=message)
