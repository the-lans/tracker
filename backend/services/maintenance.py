"""
Флаг обслуживания на время обновления сервера (раздел 20.6 ТЗ).

`deploy/install.sh --update` ставит ключ `maintenance:deploy` с TTL перед
ожиданием живых сессий и снимает его в конце обновления (и при ошибке).
Пока ключ стоит, запуск, перезапуск и автозапуск задачи отвечают 503, а
воркер сессий не берёт задачи из `queued`: они остаются в очереди и
стартуют после перезапуска сервисов.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from redis.exceptions import RedisError

from app_logging.config import get_logger
from services.errors import ServiceUnavailableError
from services.redis_connection import redis_connection

if TYPE_CHECKING:
    from redis.asyncio import Redis

logger = get_logger("maintenance")

# То же имя ключа ставит и снимает `deploy/install.sh` через redis-cli.
MAINTENANCE_KEY = "maintenance:deploy"
MAINTENANCE_MESSAGE = "Идёт обновление сервера, запустите задачу через несколько минут"


async def maintenance_active(redis_client: Redis) -> bool:
    try:
        return bool(await redis_client.exists(MAINTENANCE_KEY))
    except RedisError:
        # Флаг не прочитан — запуск не блокируется: без Redis задача всё равно
        # не стартует, а ложное «идёт обновление» сбило бы пользователя с толку.
        logger.warning("maintenance_flag_unavailable")
        return False


async def ensure_not_in_maintenance() -> None:
    async with redis_connection() as redis_client:
        if await maintenance_active(redis_client):
            raise ServiceUnavailableError(MAINTENANCE_MESSAGE)
