"""
«Системные настройки» админки (раздел 15.5 ТЗ): значения по умолчанию для
выполнения — общий таймаут и политика retry.

Таймаут и retry читаются при запуске операции: изменение действует со
следующего запуска, без пересохранения объектов. Образ
раннера в ноду не записывается: если у script-ноды он не задан явно, образ
берётся из стандартных образов в коде по её текущему языку — так смена
языка в редакторе не оставляет ноду в чужом раннере.

Здесь же — ночное окно воркера очереди (раздел 14.4): его начало задаёт и
расписание `dispatch_night_tasks`. И интеграция с GitLab: адрес и токен API (раздел 16.2,
`sync_gitlab_merge_status`). Это настройки системы, а не переменные
окружения: в промты и script-контейнеры они не попадают (раздел 19.4).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from app_logging.config import get_logger
from db.models.enums import NodeType, ScriptLanguage
from db.models.settings import SYSTEM_SETTINGS_ROW_ID, SystemSettings
from services.nodes.script import DEFAULT_RUNNER_IMAGES
from services.periodic_tasks import set_night_dispatch_schedule
from services.task_queue import night_window_cron, validate_night_window

if TYPE_CHECKING:
    from datetime import time

    from sqlalchemy.ext.asyncio import AsyncSession

    from db.models.pipelines import Node

logger = get_logger("system_settings")

# Прежние константы кода — значения строки, если её ещё нет.
DEFAULT_NODE_TIMEOUT_SECONDS = 600
DEFAULT_NODE_MAX_RETRIES = 3
DEFAULT_NODE_RETRY_BASE_DELAY_SECONDS = 5


@dataclass(frozen=True, slots=True)
class SystemSettingsValues:
    default_timeout_seconds: int
    default_max_retries: int
    default_retry_base_delay_seconds: int
    # Раздел 14.4: ночное окно по московскому времени, общее для всех.
    night_window_start: time
    night_window_end: time
    # Раздел 17.2: срок хранения журнала `app_logs`.
    app_logs_retention_days: int
    # Раздел 15.8: начало дня «Дейли» по Москве; с ночным окном не связано.
    day_start_time: time


@dataclass(frozen=True, slots=True)
class ExecutionSettings:
    timeout_seconds: int
    max_retries: int
    retry_base_delay_seconds: int


async def get_system_settings(db_session: AsyncSession) -> SystemSettings:
    """Строка настроек; создаётся со значениями по умолчанию, если её нет."""
    settings = await db_session.get(SystemSettings, SYSTEM_SETTINGS_ROW_ID)
    if settings is not None:
        return settings
    settings = SystemSettings(
        id=SYSTEM_SETTINGS_ROW_ID,
        default_timeout_seconds=DEFAULT_NODE_TIMEOUT_SECONDS,
        default_max_retries=DEFAULT_NODE_MAX_RETRIES,
        default_retry_base_delay_seconds=DEFAULT_NODE_RETRY_BASE_DELAY_SECONDS,
        # Устаревшие столбцы NOT NULL: заполняются для предыдущей версии при откате.
        default_runner_image_python=DEFAULT_RUNNER_IMAGES[ScriptLanguage.PYTHON],
        default_runner_image_bash=DEFAULT_RUNNER_IMAGES[ScriptLanguage.BASH],
    )
    db_session.add(settings)
    await db_session.commit()
    return settings


async def update_system_settings(
    db_session: AsyncSession,
    *,
    values: SystemSettingsValues,
) -> SystemSettings:
    validate_night_window(start=values.night_window_start, end=values.night_window_end)
    settings = await get_system_settings(db_session)
    if settings.night_window_start != values.night_window_start:
        await set_night_dispatch_schedule(
            db_session,
            crontab_expression=night_window_cron(values.night_window_start),
        )
    settings.night_window_start = values.night_window_start
    settings.night_window_end = values.night_window_end
    settings.default_timeout_seconds = values.default_timeout_seconds
    settings.default_max_retries = values.default_max_retries
    settings.default_retry_base_delay_seconds = values.default_retry_base_delay_seconds
    settings.app_logs_retention_days = values.app_logs_retention_days
    settings.day_start_time = values.day_start_time
    await db_session.commit()
    logger.info("system_settings_updated")
    return settings


async def resolve_execution_settings(db_session: AsyncSession) -> ExecutionSettings:
    """
    Текущая системная политика: перечитывается и в долгоживущей сессии воркера.
    """
    settings = await db_session.get(SystemSettings, SYSTEM_SETTINGS_ROW_ID, populate_existing=True)
    return ExecutionSettings(
        timeout_seconds=settings.default_timeout_seconds
        if settings
        else DEFAULT_NODE_TIMEOUT_SECONDS,
        max_retries=settings.default_max_retries if settings else DEFAULT_NODE_MAX_RETRIES,
        retry_base_delay_seconds=settings.default_retry_base_delay_seconds
        if settings
        else DEFAULT_NODE_RETRY_BASE_DELAY_SECONDS,
    )


async def resolve_runner_image(db_session: AsyncSession, node: Node) -> str | None:
    """Образ раннера для запуска script-ноды; для остальных типов — `None`."""
    if node.node_type is not NodeType.SCRIPT or node.script_language is None:
        return None
    if node.docker_image:
        return node.docker_image
    return DEFAULT_RUNNER_IMAGES[node.script_language]


async def get_jira_url(db_session: AsyncSession) -> str | None:
    """Раздел 15.6: адрес сервера Jira для импорта задач; `None` — не задан."""
    return (await get_system_settings(db_session)).jira_url


async def update_integrations(
    db_session: AsyncSession,
    *,
    jira_url: str | None,
) -> SystemSettings:
    """Раздел 15.5: адрес Jira; доступ к GitLab API — в учётных данных Git."""
    settings = await get_system_settings(db_session)
    settings.jira_url = jira_url.rstrip("/") if jira_url else None
    await db_session.commit()
    logger.info(
        "integrations_updated",
        jira_url_set=settings.jira_url is not None,
    )
    return settings
