"""Инстанс Celery (раздел 2.1, 2.2 ТЗ). Брокер и backend — Redis.

Запуск (см. CLAUDE.md, раздел 4):

- ``celery -A tasks.celery_app worker -Q celery -l info`` — периодические задачи;
- ``celery -A tasks.celery_app worker -Q sessions -O fair -l info`` — сессии задач;
- ``celery -A tasks.celery_app beat -l info`` — планировщик из `periodic_tasks`.

Сессия задачи живёт часами и ждёт решения пользователя без ограничения по
времени (раздел 9.6), поэтому у неё своя очередь и свой воркер: занятые
сессиями процессы не задерживают периодические задачи (раздел 20.3).
"""

from __future__ import annotations

import os

from celery import Celery

SESSIONS_QUEUE = "sessions"

celery_app = Celery(
    "tracker",
    broker=os.environ["REDIS_URL"],
    backend=os.environ["REDIS_URL"],
    # Модули с задачами: без них воркер не знает ни одной задачи.
    include=["tasks.session_worker", "tasks.periodic", "tasks.jira_attachments"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_routes={"run_task_session": {"queue": SESSIONS_QUEUE}},
    # Долгие задачи: процесс не резервирует следующие сообщения, пока занят.
    worker_prefetch_multiplier=1,
    # Раздел 16.1: расписание читается из таблицы `periodic_tasks`.
    beat_scheduler="tasks.periodic_scheduler:DatabaseScheduler",
)
