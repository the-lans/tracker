"""Единая конфигурация структурированного логирования (раздел 17.2 ТЗ).

JSON на stdout с обязательными полями timestamp/level/source/message —
и для structlog, и для stdlib-логгеров библиотек (uvicorn, Celery);
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

# Логгеры uvicorn со своими обработчиками и форматом (`uvicorn` ставит их до
# импорта приложения) — их записи уходят в общий JSON-обработчик.
_UVICORN_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access")


def _source_from_logger_name(
    _logger: object,
    _method_name: str,
    event_dict: structlog.typing.EventDict,
) -> structlog.typing.EventDict:
    """Запись stdlib-логгера (uvicorn, Celery, библиотеки): ``source`` — имя логгера."""
    record = event_dict.get("_record")
    if record is not None:
        event_dict.setdefault("source", record.name)
    return event_dict


def _shared_processors() -> list[structlog.typing.Processor]:
    return [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", key="timestamp"),
    ]


def _render_processors() -> list[structlog.typing.Processor]:
    return [
        structlog.processors.EventRenamer("message"),
        structlog.processors.JSONRenderer(),
    ]


def _stdlib_json_handler() -> logging.Handler:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=[*_shared_processors(), _source_from_logger_name],
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                structlog.processors.format_exc_info,
                *_render_processors(),
            ],
        ),
    )
    return handler


def configure_logging(*, level: int = logging.INFO) -> None:
    """Настроить structlog + stdlib logging один раз при старте процесса."""
    logging.basicConfig(handlers=[_stdlib_json_handler()], level=level)
    logging.captureWarnings(True)
    for name in _UVICORN_LOGGERS:
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True

    structlog.configure(
        processors=[
            *_shared_processors(),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            *_render_processors(),
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
