"""
Подключение к Redis (сигналы задач, команды управления, блокировки, пульс
сессии) — одно на операцию, в event loop вызывающего кода.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from redis.asyncio import Redis

REDIS_URL_ENV = "REDIS_URL"


@asynccontextmanager
async def redis_connection() -> AsyncIterator[Redis]:
    """Клиент Redis на время блока; соединение закрывается и при ошибке."""
    redis_client = Redis.from_url(os.environ[REDIS_URL_ENV])
    try:
        yield redis_client
    finally:
        await redis_client.aclose()
