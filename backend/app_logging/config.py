"""Единая конфигурация структурированного логирования (раздел 17.2 ТЗ).

JSON на stdout с обязательными полями timestamp/level/source/message;
task_id добавляется вызывающим кодом через ``logger.bind(task_id=...)``
или на всю обработку задачи — ``bind_task_context`` (contextvars).
Ротацию и хранение обеспечивает драйвер логирования Docker — это
применимо только к обычным (не критичным) логам; критичные события
дополнительно пишутся в таблицу ``app_logs`` вызывающим кодом.
"""

from __future__ import annotations

import logging
import sys
import uuid
from collections.abc import Iterator
from contextlib import contextmanager

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
        # Без кеша: логгер, успевший записать до этой настройки, иначе навсегда
        # остался бы с форматом по умолчанию.
        cache_logger_on_first_use=False,
    )


def get_logger(source: str) -> structlog.typing.FilteringBoundLogger:
    """
    Логгер с обязательным полем ``source`` (модуль/сервис).

    Ленивый: модули создают логгер при импорте, раньше ``configure_logging()``,
    а настройки structlog применяются при первой записи — иначе такой логгер
    навсегда остался бы с консольным форматом по умолчанию вместо JSON.
    """
    logger: structlog.typing.FilteringBoundLogger = structlog.get_logger(source=source)
    return logger


@contextmanager
def bind_task_context(task_id: uuid.UUID) -> Iterator[None]:
    """
    ``task_id`` во всех событиях, записанных при обработке задачи, — в том
    числе в общих сервисах, которые о задаче не знают (клонирование,
    сессия, скрипт-ноды): по нему ищутся все логи задачи (раздел 17.2).
    """
    with structlog.contextvars.bound_contextvars(task_id=str(task_id)):
        yield
