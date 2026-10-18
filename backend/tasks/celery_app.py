"""Инстанс Celery (раздел 2.1, 2.2 ТЗ). Брокер и backend — Redis.

Запуск: ``celery -A tasks.celery_app worker -l info`` /
``celery -A tasks.celery_app beat -l info`` (см. CLAUDE.md, раздел 4).
"""

from __future__ import annotations

import os

from celery import Celery

celery_app = Celery(
    "tracker",
    broker=os.environ["REDIS_URL"],
    backend=os.environ["REDIS_URL"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
)
