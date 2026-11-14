"""
Общий каркас периодических проходов по завершённым задачам (разделы 6.4,
14.2, 14.3 ТЗ): архивация, очистка репозиториев, удаление истории сессии и
артефактов.

Проход идёт под распределённой блокировкой (второй запуск, пока идёт первый,
ничего не делает), кандидаты — снимки `FinishedTask`, а изменение каждой
задачи — в своей транзакции: compare-and-swap статуса или строка под
`SELECT … FOR UPDATE`. Задача, которую нельзя обработать сейчас, пропускается
до следующего запуска, поэтому повтор ничего не делает дважды.
"""

from __future__ import annotations

import asyncio
import shutil
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, ClassVar

from app_logging.config import get_logger
from services.distributed_lock import LockNotAcquiredError, acquire_lock

if TYPE_CHECKING:
    from datetime import datetime
    from pathlib import Path

    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncSession

    from db.queries.finished_tasks import FinishedTask
    from services.errors import ConflictError

logger = get_logger("task_passes")

# Проход идёт раз в час: блокировка живёт чуть меньше интервала.
PASS_LOCK_TTL_SECONDS = 55 * 60


@dataclass(slots=True)
class PassResult:
    """
    Итог прохода: какие задачи изменены, какие пропущены до следующего часа.
    """

    done: list[uuid.UUID] = field(default_factory=list)
    skipped: list[uuid.UUID] = field(default_factory=list)
    lock_busy: bool = False


async def remove_directory(path: Path) -> None:
    """Удаляет каталог вне event loop; отсутствующий каталог — не ошибка."""
    await asyncio.to_thread(shutil.rmtree, path, ignore_errors=True)


class TaskPass(ABC):
    """
    Проход: выбрать кандидатов и обработать каждого под блокировкой прохода.
    """

    lock_key: ClassVar[str]
    busy_message: ClassVar[str]
    skipped_event: ClassVar[str]

    def __init__(self, db_session: AsyncSession, *, now: datetime) -> None:
        self.db_session = db_session
        self.now = now

    @abstractmethod
    async def candidates(self) -> list[FinishedTask]:
        """Задачи, которым пора в проход, — по состоянию на `now`."""

    @abstractmethod
    async def handle(self, task: FinishedTask) -> bool:
        """Обработать задачу; False — пропущена до следующего запуска."""

    async def run(self, redis_client: Redis) -> PassResult:
        result = PassResult()
        try:
            async with acquire_lock(
                redis_client,
                self.lock_key,
                ttl_seconds=PASS_LOCK_TTL_SECONDS,
                busy_message=self.busy_message,
            ):
                for task in await self.candidates():
                    (result.done if await self.handle(task) else result.skipped).append(task.id)
        except LockNotAcquiredError:
            logger.info("task_pass_already_running", lock_key=self.lock_key)
            result.lock_busy = True
        return result

    async def skip(self, task_id: uuid.UUID, exc: ConflictError) -> bool:
        """
        Откатывает транзакцию задачи и пишет причину пропуска. После отката
        ORM-объект задачи просрочен — id передаётся отдельно.
        """
        await self.db_session.rollback()
        logger.info(self.skipped_event, task_id=str(task_id), reason=str(exc))
        return False
