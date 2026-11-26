"""Очистка состояния единственного backup-worker перед приёмом задач."""

import asyncio

from db.session import async_session_factory, engine
from services.backup.runs import BACKUP_LOCK_KEY, close_runs_after_worker_restart
from services.redis_connection import redis_connection


async def prepare() -> None:
    async with async_session_factory() as db_session, redis_connection() as redis_client:
        await close_runs_after_worker_restart(db_session)
        # Старый контейнер единственного backup-worker уже остановлен.
        await redis_client.delete(BACKUP_LOCK_KEY)
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(prepare())
