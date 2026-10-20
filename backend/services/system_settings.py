"""
«Системные настройки» админки (раздел 15.5 ТЗ): значения по умолчанию для
новых нод — таймаут, политика retry и Docker-образ раннера script-ноды.

Таймаут и retry подставляются в момент создания ноды (раздел 15.5: «для
новых нод»), поэтому их изменение не трогает уже созданные ноды. Образ
раннера в ноду не записывается: если у script-ноды он не задан явно, образ
берётся из настроек при каждом запуске по её текущему языку — так смена
языка в редакторе не оставляет ноду в чужом раннере.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from app_logging.config import get_logger
from db.models.enums import NodeType, ScriptLanguage
from db.models.settings import SYSTEM_SETTINGS_ROW_ID, SystemSettings
from services.nodes.script import DEFAULT_RUNNER_IMAGES

if TYPE_CHECKING:
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
    default_runner_image_python: str
    default_runner_image_bash: str


@dataclass(frozen=True, slots=True)
class NodeExecutionDefaults:
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
    settings = await get_system_settings(db_session)
    settings.default_timeout_seconds = values.default_timeout_seconds
    settings.default_max_retries = values.default_max_retries
    settings.default_retry_base_delay_seconds = values.default_retry_base_delay_seconds
    settings.default_runner_image_python = values.default_runner_image_python
    settings.default_runner_image_bash = values.default_runner_image_bash
    await db_session.commit()
    logger.info("system_settings_updated")
    return settings


def default_runner_image(settings: SystemSettings, language: ScriptLanguage) -> str:
    if language is ScriptLanguage.PYTHON:
        return settings.default_runner_image_python
    return settings.default_runner_image_bash


async def resolve_node_execution_defaults(
    db_session: AsyncSession,
    *,
    timeout_seconds: int | None,
    max_retries: int | None,
    retry_base_delay_seconds: int | None,
) -> NodeExecutionDefaults:
    """Значения новой ноды: заданные явно остаются, пустые — из настроек."""
    settings = await get_system_settings(db_session)
    return NodeExecutionDefaults(
        timeout_seconds=(
            timeout_seconds if timeout_seconds is not None else settings.default_timeout_seconds
        ),
        max_retries=max_retries if max_retries is not None else settings.default_max_retries,
        retry_base_delay_seconds=(
            retry_base_delay_seconds
            if retry_base_delay_seconds is not None
            else settings.default_retry_base_delay_seconds
        ),
    )


async def resolve_runner_image(db_session: AsyncSession, node: Node) -> str | None:
    """Образ раннера для запуска script-ноды; для остальных типов — `None`."""
    if node.node_type is not NodeType.SCRIPT or node.script_language is None:
        return None
    if node.docker_image:
        return node.docker_image
    settings = await get_system_settings(db_session)
    return default_runner_image(settings, node.script_language)
