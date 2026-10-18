"""Единая конфигурация структурированного логирования (раздел 17.2 ТЗ).

JSON на stdout с обязательными полями timestamp/level/source/message;
task_id добавляется вызывающим кодом через ``logger.bind(task_id=...)``,
когда применимо. Ротацию и хранение обеспечивает драйвер логирования
Docker — это применимо только к обычным (не критичным) логам; критичные
события дополнительно пишутся в таблицу ``app_logs`` вызывающим кодом.
"""

from __future__ import annotations

import logging
import sys

import structlog


def configure_logging(*, level: int = logging.INFO) -> None:
    """Настроить structlog + stdlib logging один раз при старте процесса."""
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", key="timestamp"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.EventRenamer("message"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(source: str) -> structlog.typing.FilteringBoundLogger:
    """Логгер с обязательным полем ``source`` (модуль/сервис)."""
    logger: structlog.typing.FilteringBoundLogger = structlog.get_logger()
    return logger.bind(source=source)
