"""
Отдельная очередь исполнения проверок и восстановления их ресурсов.
"""

import uuid

from db.models.test_runs import TestRun
from db.session import async_session_factory
from services.test_agent import execute_ci_agent
from services.test_runs import cleanup_run, execute_run
from tasks.async_runner import run_with_fresh_pool
from tasks.celery_app import celery_app


@celery_app.task(name="execute_test_run")
def execute_test_run(run_id: str) -> None:
    run_with_fresh_pool(_execute(uuid.UUID(run_id)))


async def _execute(run_id: uuid.UUID) -> None:
    async with async_session_factory() as db:
        run = await db.get(TestRun, run_id)
    if run is not None and run.source == "ci-agent":
        await execute_ci_agent(run_id)
    else:
        await execute_run(run_id)


@celery_app.task(
    name="cleanup_test_run",
    autoretry_for=(RuntimeError, OSError, TimeoutError),
    retry_backoff=True,
    max_retries=5,
)
def cleanup_test_run(run_id: str) -> None:
    run_with_fresh_pool(cleanup_run(uuid.UUID(run_id)))
