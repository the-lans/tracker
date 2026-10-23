"""
`tasks/celery_app.py` (раздел 2.1, 16.1, 20.3 ТЗ): воркер, запущенный командой
из `docker-compose.yml`, знает все задачи, beat читает расписание из БД,
сессии задач идут в свою очередь.

Регистрация проверяется в отдельном процессе: в процессе pytest модули задач
уже импортированы другими тестами, и проверка прошла бы и без `include`.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from tests.test_seed_periodic_tasks import _load_seed_module

_BACKEND_DIR = Path(__file__).resolve().parents[1]
_PROBE = """
import json
from tasks.celery_app import celery_app
celery_app.loader.import_default_modules()
print(json.dumps({
    "tasks": sorted(name for name in celery_app.tasks if not name.startswith("celery.")),
    "beat_scheduler": celery_app.conf.beat_scheduler,
    "routes": celery_app.conf.task_routes,
    "prefetch": celery_app.conf.worker_prefetch_multiplier,
}))
"""


@pytest.fixture(scope="module")
def worker_view() -> dict[str, Any]:
    """То, что видит процесс `celery -A tasks.celery_app worker`."""
    env = {**os.environ, "REDIS_URL": "redis://localhost:1/0"}
    result = subprocess.run(
        [sys.executable, "-c", _PROBE],
        cwd=_BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    view: dict[str, Any] = json.loads(result.stdout.strip().splitlines()[-1])
    return view


class TestRegistration:
    def test_session_task_registered(self, worker_view: dict[str, Any]) -> None:
        assert "run_task_session" in worker_view["tasks"]

    def test_every_seeded_periodic_task_registered(self, worker_view: dict[str, Any]) -> None:
        seeded = {entry[0] for entry in _load_seed_module()._SEED_TASKS}
        assert seeded <= set(worker_view["tasks"])


class TestConfig:
    def test_beat_reads_schedule_from_database(self, worker_view: dict[str, Any]) -> None:
        assert worker_view["beat_scheduler"] == "tasks.periodic_scheduler:DatabaseScheduler"

    def test_sessions_have_own_queue(self, worker_view: dict[str, Any]) -> None:
        assert worker_view["routes"] == {"run_task_session": {"queue": "sessions"}}
        assert worker_view["prefetch"] == 1
