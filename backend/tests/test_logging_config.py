"""
`app_logging/config.py` (раздел 17.2 ТЗ): все логи процесса — JSON, в том числе
от логгеров, созданных при импорте модулей до `configure_logging()`, и в
процессах Celery.

Проверка — в отдельном процессе: в процессе pytest structlog уже настроен
по-своему и логгеры модулей уже созданы.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

import pytest

_BACKEND_DIR = Path(__file__).resolve().parents[1]
_TASK_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")

_API_PROBE = f"""
import uuid
from app_logging.config import bind_task_context, configure_logging, get_logger
early = get_logger("early")
configure_logging()
with bind_task_context(uuid.UUID("{_TASK_ID}")):
    early.info("probe_event", answer=42)
"""

_CELERY_PROBE = """
from celery import signals
from app_logging.config import get_logger
from tasks.celery_app import celery_app
early = get_logger("early")
signals.setup_logging.send(sender=None, loglevel="INFO", logfile=None, format="", colorize=False)
early.info("probe_event")
print("REDIRECT", celery_app.conf.worker_redirect_stdouts)
"""


def _run_probe(code: str) -> list[str]:
    env = {**os.environ, "REDIS_URL": "redis://localhost:1/0"}
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=_BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip().splitlines()


def _event(lines: list[str]) -> dict[str, Any]:
    entry: dict[str, Any] = json.loads(next(line for line in lines if "probe_event" in line))
    return entry


class TestJsonLogs:
    def test_logger_created_before_configure(self) -> None:
        entry = _event(_run_probe(_API_PROBE))

        assert entry["message"] == "probe_event"
        assert (entry["source"], entry["level"], entry["answer"]) == ("early", "info", 42)
        assert "timestamp" in entry

    def test_task_context_adds_task_id(self) -> None:
        assert _event(_run_probe(_API_PROBE))["task_id"] == str(_TASK_ID)

    @pytest.mark.parametrize("probe", ["event", "redirect"])
    def test_celery_process(self, probe: str) -> None:
        lines = _run_probe(_CELERY_PROBE)

        if probe == "event":
            assert _event(lines)["source"] == "early"
        else:
            assert "REDIRECT False" in lines
