"""
Запуск асинхронного кода из синхронной Celery-задачи и планировщика Beat.

Каждый `asyncio.run` создаёт новый event loop, а соединения пула SQLAlchemy
привязаны к loop, в котором открыты: следующая задача в том же процессе
получила бы соединение чужого loop («attached to a different loop»). Поэтому
пул освобождается в конце каждого запуска, в его же loop.
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any

from db.session import engine


def run_with_fresh_pool[T](coroutine: Coroutine[Any, Any, T]) -> T:
    async def runner() -> T:
        try:
            return await coroutine
        finally:
            await engine.dispose()

    return asyncio.run(runner())
