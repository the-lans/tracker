"""Ручной запуск, история и очистка проверок задачи."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

import sqlalchemy as sa
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_current_user
from api.schemas.test_runs import StartTestRunRequest, TestRunResponse
from api.tasks.common import get_task_or_404
from db.models.test_runs import TestRun
from db.models.users import User
from db.session import get_session
from services.errors import ConflictError, NotFoundError
from services.test_runs import ACTIVE_STATUSES, create_run
from tasks.test_runs import cleanup_test_run, execute_test_run

router = APIRouter(prefix="/tasks", tags=["tasks"])
Db = Annotated[AsyncSession, Depends(get_session)]
CurrentUser = Annotated[User, Depends(get_current_user)]


async def owned_run(db: AsyncSession, task_id: uuid.UUID, run_id: uuid.UUID) -> TestRun:
    run = await db.get(TestRun, run_id)
    if run is None or run.task_id != task_id:
        raise NotFoundError("Прогон не найден")
    return run


@router.post("/{task_id}/test-runs", response_model=TestRunResponse, status_code=201)
async def start_test_run(
    task_id: uuid.UUID,
    body: StartTestRunRequest,
    db_session: Db,
    current_user: CurrentUser,
) -> TestRun:
    task = await get_task_or_404(db_session, task_id, current_user)
    run = await create_run(
        db_session,
        task=task,
        repository_id=body.repository_id,
        check=body.check,
        source="manual",
        idempotency_key=body.idempotency_key,
    )
    execute_test_run.delay(str(run.id))
    return run


@router.get("/{task_id}/test-runs", response_model=list[TestRunResponse])
async def list_test_runs(
    task_id: uuid.UUID,
    db_session: Db,
    current_user: CurrentUser,
) -> list[dict[str, Any]]:
    await get_task_or_404(db_session, task_id, current_user)
    columns = [getattr(TestRun, field) for field in TestRunResponse.model_fields if field != "logs"]
    rows = await db_session.execute(
        sa.select(*columns)
        .where(
            TestRun.task_id == task_id,
        )
        .order_by(TestRun.created_at.desc())
        .limit(100)
    )
    return [dict(row) for row in rows.mappings()]


@router.get("/{task_id}/test-runs/{run_id}", response_model=TestRunResponse)
async def get_test_run(
    task_id: uuid.UUID,
    run_id: uuid.UUID,
    db_session: Db,
    current_user: CurrentUser,
) -> TestRun:
    await get_task_or_404(db_session, task_id, current_user)
    return await owned_run(db_session, task_id, run_id)


@router.post("/{task_id}/test-runs/{run_id}/stop", response_model=TestRunResponse)
async def stop_test_run(
    task_id: uuid.UUID,
    run_id: uuid.UUID,
    db_session: Db,
    current_user: CurrentUser,
) -> TestRun:
    await get_task_or_404(db_session, task_id, current_user)
    run = await owned_run(db_session, task_id, run_id)
    if run.status in ACTIVE_STATUSES:
        run.cancel_requested = True
        await db_session.commit()
        execute_test_run.delay(str(run.id))
    return run


@router.post("/{task_id}/test-runs/{run_id}/cleanup", status_code=202)
async def retry_test_cleanup(
    task_id: uuid.UUID,
    run_id: uuid.UUID,
    db_session: Db,
    current_user: CurrentUser,
) -> None:
    await get_task_or_404(db_session, task_id, current_user)
    run = await owned_run(db_session, task_id, run_id)
    if run.status in ACTIVE_STATUSES:
        raise ConflictError("Сначала остановите выполняющийся прогон")
    cleanup_test_run.delay(str(run.id))
