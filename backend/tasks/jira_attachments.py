"""
Копирование вложений задачи Jira в артефакты новой задачи (раздел 15.6 ТЗ).

Идёт в фоне, а не в запросе создания задачи: вложений может быть много, и
ответ «задача создана» не ждёт их загрузки. Повторная доставка безопасна —
те же вложения записываются под теми же именами. По окончании, в том числе
после сбоя, снимается флаг «вложения копируются», по которому страница
задачи перечитывает артефакты.
"""

from __future__ import annotations

import os
import uuid

from redis.asyncio import Redis

from app_logging.config import get_logger
from db.models.tasks import Task
from db.models.users import User
from db.session import async_session_factory
from services.jira_import import (
    clear_attachment_copy_pending,
    copy_jira_attachments,
    new_jira_http_client,
)
from tasks.async_runner import run_with_fresh_pool
from tasks.celery_app import celery_app

logger = get_logger("jira_attachments")


async def _copy(*, task_id: uuid.UUID, user_id: uuid.UUID, key: str) -> None:
    async with async_session_factory() as db_session:
        task = await db_session.get(Task, task_id)
        user = await db_session.get(User, user_id)
        if task is None or user is None:
            logger.warning("jira_attachments_target_missing", task_id=str(task_id))
            return
        async with new_jira_http_client() as http_client:
            await copy_jira_attachments(
                db_session,
                task=task,
                user=user,
                key=key,
                http_client=http_client,
            )


async def copy_jira_attachments_async(*, task_id: uuid.UUID, user_id: uuid.UUID, key: str) -> None:
    try:
        await _copy(task_id=task_id, user_id=user_id, key=key)
    finally:
        redis_client = Redis.from_url(os.environ["REDIS_URL"])
        try:
            await clear_attachment_copy_pending(redis_client, task_id)
        finally:
            await redis_client.aclose()


@celery_app.task(name="copy_jira_attachments_to_task")
def copy_jira_attachments_to_task(task_id: str, user_id: str, key: str) -> None:
    run_with_fresh_pool(
        copy_jira_attachments_async(
            task_id=uuid.UUID(task_id),
            user_id=uuid.UUID(user_id),
            key=key,
        ),
    )
