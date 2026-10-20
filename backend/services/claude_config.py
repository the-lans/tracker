"""
Срок хранения истории сессий Claude Code (раздел 6.4 ТЗ).

CLI сам удаляет старые истории сессий (`cleanupPeriodDays` в
`settings.json` конфигурационной директории). Задачи трекера не удаляются,
а продолжение сессии (resume) и пересказ для дочерней задачи читают эту
историю — поэтому срок выставляется не меньше заданного, перед каждым
подключением к сессии.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from app_logging.config import get_logger

logger = get_logger("claude_config")

_SETTINGS_FILE = "settings.json"
_CLEANUP_PERIOD_KEY = "cleanupPeriodDays"
_RETENTION_ENV_VAR = "CLAUDE_SESSION_RETENTION_DAYS"
# Задачи в системе не удаляются — по умолчанию сто лет.
DEFAULT_HISTORY_RETENTION_DAYS = 36500
_JSON_INDENT = 2


def history_retention_days() -> int:
    return int(os.environ.get(_RETENTION_ENV_VAR, DEFAULT_HISTORY_RETENTION_DAYS))


def _write_atomically(path: Path, content: str) -> None:
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def ensure_history_retention(config_dir: str, *, days: int) -> None:
    """
    Выставляет `cleanupPeriodDays` не меньше ``days``, сохраняя остальные ключи.

    Больший срок, заданный вручную, не уменьшается. Повреждённый файл не
    перезаписывается: это чужая настройка, её правят руками.
    """
    if not config_dir:
        return
    settings_path = Path(config_dir) / _SETTINGS_FILE
    settings: dict[str, object] = {}
    if settings_path.exists():
        try:
            loaded = json.loads(settings_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            logger.warning("claude_settings_unreadable", path=str(settings_path))
            return
        if not isinstance(loaded, dict):
            logger.warning("claude_settings_not_an_object", path=str(settings_path))
            return
        settings = loaded
    current = settings.get(_CLEANUP_PERIOD_KEY)
    if isinstance(current, int) and current >= days:
        return
    settings[_CLEANUP_PERIOD_KEY] = days
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    _write_atomically(settings_path, json.dumps(settings, ensure_ascii=False, indent=_JSON_INDENT))
    logger.info("claude_history_retention_set", path=str(settings_path), days=days)
