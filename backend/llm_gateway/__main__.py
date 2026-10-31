"""`python -m llm_gateway` — точка входа сервиса `llm-gateway` (docker-compose.yml)."""

from __future__ import annotations

import asyncio
import os

import httpx
import uvicorn
from redis.asyncio import Redis

from app_logging.config import configure_logging, get_logger
from llm_gateway.app import create_app
from llm_gateway.config import LOGGER_NAME, load_config
from services.redis_connection import REDIS_URL_ENV

logger = get_logger(LOGGER_NAME)

# Наружу порт не публикуется: шлюз доступен только сервисам compose.
_LISTEN_HOST = "0.0.0.0"
# Ход модели длится минутами: ждём только соединения, не ответа.
_UPSTREAM_TIMEOUT = httpx.Timeout(None, connect=10.0)


async def _serve() -> None:
    config = load_config()
    redis_client = Redis.from_url(os.environ[REDIS_URL_ENV])
    async with httpx.AsyncClient(timeout=_UPSTREAM_TIMEOUT) as upstream:
        app = create_app(config=config, redis_client=redis_client, upstream=upstream)
        server = uvicorn.Server(
            uvicorn.Config(app, host=_LISTEN_HOST, port=config.port, log_config=None),
        )
        logger.info("llm_gateway_started", port=config.port)
        try:
            await server.serve()
        finally:
            await redis_client.aclose()
    logger.info("llm_gateway_stopped")


def main() -> None:
    configure_logging()
    asyncio.run(_serve())


if __name__ == "__main__":
    main()
