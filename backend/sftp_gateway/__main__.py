"""`python -m sftp_gateway` — точка входа сервиса `sftp` (docker-compose.yml)."""

from __future__ import annotations

import asyncio
import signal

from app_logging.config import configure_logging, get_logger
from db.session import async_session_factory
from sftp_gateway.config import LOGGER_NAME, load_config
from sftp_gateway.host_key import load_or_create_host_key
from sftp_gateway.server import check_database, start_server

logger = get_logger(LOGGER_NAME)


async def _serve() -> None:
    config = load_config()
    await check_database(async_session_factory)
    host_key = load_or_create_host_key(config.host_key_path)
    acceptor = await start_server(
        config=config,
        session_factory=async_session_factory,
        host_key=host_key,
    )
    stopped = asyncio.Event()
    loop = asyncio.get_running_loop()
    for stop_signal in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(stop_signal, stopped.set)
    logger.info("sftp_gateway_started", port=config.port)
    await stopped.wait()
    acceptor.close()
    await acceptor.wait_closed()
    logger.info("sftp_gateway_stopped")


def main() -> None:
    configure_logging()
    asyncio.run(_serve())


if __name__ == "__main__":
    main()
