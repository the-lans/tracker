"""
Миграция `a1d5f8c3e047` (разделы 3.1, 19.7): прежние аккаунты получают
префикс учётки прокси, место в порядке переключения и статус
`login_required`, задачи — мост `unavailable`; откат и повторное применение
не падают.

Проверяется на отдельной временной базе того же тестового Postgres, чтобы не
трогать схему, на которой идут остальные тесты.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from tests.migration_support import run_alembic

_PREVIOUS_REVISION = "f4c2a8e6b913"
_REVISION = "a1d5f8c3e047"
_FIRST_ACCOUNT_ID = uuid.UUID("0a1b2c3d-4e5f-4061-8293-a4b5c6d7e8f9")
_SECOND_ACCOUNT_ID = uuid.UUID("1a2b3c4d-5e6f-4071-8293-a4b5c6d7e8f9")


@dataclass(frozen=True)
class _OldLayout:
    owner_id: uuid.UUID
    other_owner_id: uuid.UUID
    task_id: uuid.UUID


async def _insert_user(connection: sa.AsyncConnection, email: str) -> uuid.UUID:
    user_id = uuid.uuid4()
    await connection.execute(
        sa.text("INSERT INTO users (id, email, role, is_active) VALUES (:id, :email, 'user', true)"),
        {"id": user_id, "email": email},
    )
    return user_id


async def _insert_account(
    connection: sa.AsyncConnection,
    *,
    account_id: uuid.UUID,
    owner_id: uuid.UUID,
    created_at: datetime,
) -> None:
    await connection.execute(
        sa.text(
            "INSERT INTO llm_accounts (id, label, claude_config_dir, status, created_by, created_at) "
            "VALUES (:id, 'main', :dir, 'active', :owner, :created_at)",
        ),
        {
            "id": account_id,
            "dir": f"/data/claude-accounts/{account_id.hex}",
            "owner": owner_id,
            "created_at": created_at,
        },
    )


async def _seed_old_layout(engine: AsyncEngine) -> _OldLayout:
    async with engine.begin() as connection:
        owner_id = await _insert_user(connection, "owner@example.com")
        other_owner_id = await _insert_user(connection, "other@example.com")
        # Второй аккаунт заведён раньше — он первый в порядке переключения.
        await _insert_account(
            connection,
            account_id=_FIRST_ACCOUNT_ID,
            owner_id=owner_id,
            created_at=datetime(2026, 10, 2, tzinfo=UTC),
        )
        await _insert_account(
            connection,
            account_id=_SECOND_ACCOUNT_ID,
            owner_id=owner_id,
            created_at=datetime(2026, 10, 1, tzinfo=UTC),
        )
        await _insert_account(
            connection,
            account_id=uuid.uuid4(),
            owner_id=other_owner_id,
            created_at=datetime(2026, 10, 3, tzinfo=UTC),
        )
        task_id = uuid.uuid4()
        await connection.execute(
            sa.text(
                "INSERT INTO tasks (id, code, title, description, status, use_parent_summary, "
                "auto_accept_plan, remote_control_status, remote_control_reconnect_attempts, "
                "auto_start_enabled, created_by) VALUES (:id, 'RR-1', 't', '', 'done', false, "
                "false, 'connected', 0, false, :owner)",
            ),
            {"id": task_id, "owner": owner_id},
        )
    return _OldLayout(owner_id=owner_id, other_owner_id=other_owner_id, task_id=task_id)


@pytest_asyncio.fixture
async def migrated(scratch_database: str) -> AsyncIterator[tuple[AsyncEngine, _OldLayout, str]]:
    """База на ревизии миграции с данными, заведёнными до неё."""
    run_alembic(scratch_database, "upgrade", _PREVIOUS_REVISION)
    engine = create_async_engine(scratch_database)
    try:
        layout = await _seed_old_layout(engine)
        run_alembic(scratch_database, "upgrade", _REVISION)
        yield engine, layout, scratch_database
    finally:
        await engine.dispose()


class TestLlmProxyRoutingMigration:
    async def test_existing_accounts_get_prefix_and_order(
        self,
        migrated: tuple[AsyncEngine, _OldLayout, str],
    ) -> None:
        engine, layout, _ = migrated
        async with engine.connect() as connection:
            rows = (
                await connection.execute(
                    sa.text(
                        "SELECT id, cliproxy_prefix, switch_order, status::text, provider, "
                        "default_effort::text FROM llm_accounts WHERE created_by = :owner "
                        "ORDER BY switch_order",
                    ),
                    {"owner": layout.owner_id},
                )
            ).all()
        assert [(row.id, row.cliproxy_prefix, row.switch_order) for row in rows] == [
            (_SECOND_ACCOUNT_ID, "acc-1a2b3c4d5e6f", 1),
            (_FIRST_ACCOUNT_ID, "acc-0a1b2c3d4e5f", 2),
        ]
        assert {(row.status, row.provider, row.default_effort) for row in rows} == {
            ("login_required", "anthropic", "high"),
        }

    async def test_order_starts_per_owner(
        self,
        migrated: tuple[AsyncEngine, _OldLayout, str],
    ) -> None:
        engine, layout, _ = migrated
        async with engine.connect() as connection:
            order = await connection.scalar(
                sa.text("SELECT switch_order FROM llm_accounts WHERE created_by = :owner"),
                {"owner": layout.other_owner_id},
            )
        assert order == 1

    async def test_users_and_tasks_defaults(
        self,
        migrated: tuple[AsyncEngine, _OldLayout, str],
    ) -> None:
        engine, layout, _ = migrated
        async with engine.connect() as connection:
            thresholds = (
                await connection.execute(
                    sa.text(
                        "SELECT llm_switch_threshold_5h_pct, llm_switch_threshold_week_pct "
                        "FROM users WHERE id = :id",
                    ),
                    {"id": layout.owner_id},
                )
            ).one()
            bridge = await connection.scalar(
                sa.text("SELECT remote_control_status::text FROM tasks WHERE id = :id"),
                {"id": layout.task_id},
            )
        assert tuple(thresholds) == (93, 93)
        assert bridge == "unavailable"

    @pytest.mark.parametrize("value", [0, 101])
    async def test_threshold_out_of_range_rejected(
        self,
        migrated: tuple[AsyncEngine, _OldLayout, str],
        value: int,
    ) -> None:
        engine, layout, _ = migrated
        with pytest.raises(sa.exc.IntegrityError):
            async with engine.begin() as connection:
                await connection.execute(
                    sa.text("UPDATE users SET llm_switch_threshold_5h_pct = :value WHERE id = :id"),
                    {"value": value, "id": layout.owner_id},
                )

    async def test_switch_order_unique_per_owner_at_commit(
        self,
        migrated: tuple[AsyncEngine, _OldLayout, str],
    ) -> None:
        engine, layout, _ = migrated
        swap = (
            "UPDATE llm_accounts SET switch_order = CASE switch_order WHEN 1 THEN 2 ELSE 1 END "
            "WHERE created_by = :owner"
        )
        async with engine.begin() as connection:
            await connection.execute(sa.text(swap), {"owner": layout.owner_id})
        with pytest.raises(sa.exc.IntegrityError):
            async with engine.begin() as connection:
                await connection.execute(
                    sa.text("UPDATE llm_accounts SET switch_order = 1 WHERE created_by = :owner"),
                    {"owner": layout.owner_id},
                )

    async def test_downgrade_and_upgrade_again(
        self,
        migrated: tuple[AsyncEngine, _OldLayout, str],
    ) -> None:
        engine, layout, database_url = migrated
        run_alembic(database_url, "downgrade", _PREVIOUS_REVISION)
        async with engine.connect() as connection:
            statuses = set(
                (
                    await connection.execute(sa.text("SELECT status::text FROM llm_accounts"))
                ).scalars(),
            )
            bridge = await connection.scalar(
                sa.text("SELECT remote_control_status::text FROM tasks WHERE id = :id"),
                {"id": layout.task_id},
            )
        assert statuses == {"disabled"}
        assert bridge == "disconnected"

        run_alembic(database_url, "upgrade", _REVISION)
        async with engine.connect() as connection:
            prefixes = await connection.scalar(
                sa.text("SELECT count(*) FROM llm_accounts WHERE cliproxy_prefix LIKE 'acc-%'"),
            )
        assert prefixes == 3
