"""
Миграция `a7e2c9d4b185`: статус запроса очереди `injected` (раздел 7.3).
Проверяется на отдельной временной базе: значение добавляется, откат возвращает
такие запросы в очередь (значение enum остаётся — раздел 20.6).
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from tests.migration_support import run_alembic

_PREVIOUS_REVISION = "e1a7c3b9d264"
_REVISION = "a7e2c9d4b185"
_SET_INJECTED = "UPDATE task_manual_request_queue SET status = 'injected' WHERE id = :id"


async def _seed_request(engine: AsyncEngine) -> uuid.UUID:
    user_id, task_id, request_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    async with engine.begin() as connection:
        await connection.execute(
            sa.text(
                "INSERT INTO users (id, email, role, is_active) VALUES (:id, :email, 'user', true)",
            ),
            {"id": user_id, "email": f"{user_id}@example.com"},
        )
        await connection.execute(
            sa.text(
                "INSERT INTO tasks (id, code, title, description, status, use_parent_summary, "
                "auto_accept_plan, remote_control_status, remote_control_reconnect_attempts, "
                "auto_start_enabled, created_by) VALUES (:id, :code, 't', 'd', 'in_progress', "
                "false, false, 'unavailable', 0, false, :user_id)",
            ),
            {"id": task_id, "code": f"RR-{task_id.hex[:8]}", "user_id": user_id},
        )
        await connection.execute(
            sa.text(
                "INSERT INTO task_manual_request_queue (id, task_id, request_type, "
                "raw_prompt_text, requested_by, requested_at, status) VALUES (:id, :task_id, "
                "'freeform_prompt', 'влитый', :user_id, now(), 'queued')",
            ),
            {"id": request_id, "task_id": task_id, "user_id": user_id},
        )
    return request_id


async def _labels(engine: AsyncEngine) -> set[str]:
    async with engine.connect() as connection:
        rows = await connection.execute(
            sa.text("SELECT unnest(enum_range(NULL::manual_request_status))::text"),
        )
        return {row[0] for row in rows}


class TestManualRequestInjectedMigration:
    async def test_adds_the_status_and_accepts_it(self, scratch_database: str) -> None:
        run_alembic(scratch_database, "upgrade", _PREVIOUS_REVISION)
        engine = create_async_engine(scratch_database)
        try:
            assert "injected" not in await _labels(engine)
            request_id = await _seed_request(engine)
            run_alembic(scratch_database, "upgrade", _REVISION)
            assert "injected" in await _labels(engine)
            async with engine.begin() as connection:
                await connection.execute(
                    sa.text(
                        "UPDATE task_manual_request_queue SET status = 'injected' WHERE id = :id"
                    ),
                    {"id": request_id},
                )
        finally:
            await engine.dispose()

    async def test_repeated_upgrade_is_harmless(self, scratch_database: str) -> None:
        run_alembic(scratch_database, "upgrade", _REVISION)
        run_alembic(scratch_database, "downgrade", _PREVIOUS_REVISION)
        run_alembic(scratch_database, "upgrade", _REVISION)
        engine = create_async_engine(scratch_database)
        try:
            assert "injected" in await _labels(engine)
        finally:
            await engine.dispose()

    async def test_downgrade_requeues(
        self,
        scratch_database: str,
    ) -> None:
        run_alembic(scratch_database, "upgrade", _PREVIOUS_REVISION)
        engine = create_async_engine(scratch_database)
        try:
            request_id = await _seed_request(engine)
            run_alembic(scratch_database, "upgrade", _REVISION)
            async with engine.begin() as connection:
                await connection.execute(
                    sa.text(
                        "UPDATE task_manual_request_queue SET status = 'injected' WHERE id = :id"
                    ),
                    {"id": request_id},
                )
            run_alembic(scratch_database, "downgrade", _PREVIOUS_REVISION)
            async with engine.connect() as connection:
                status = (
                    await connection.execute(
                        sa.text("SELECT status::text FROM task_manual_request_queue"),
                    )
                ).scalar_one()
        finally:
            await engine.dispose()
        # Значение enum остаётся (миграции только добавляют), запрос — снова в очереди.
        assert status == "queued"
