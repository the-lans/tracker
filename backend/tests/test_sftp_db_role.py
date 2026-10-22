"""
`sftp_gateway/db_role.py` (раздел 20.5 ТЗ): роль шлюза делает всё, что нужно
`services/sftp_access.py` и аудиту, и не видит остального.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from db.models.enums import AppLogLevel
from db.models.logs import AppLog
from db.models.tasks import Task
from db.models.users import User
from services.sftp_access import (
    find_sftp_login,
    is_task_visible,
    list_visible_task_codes,
    touch_ssh_key_usage,
)
from sftp_gateway.db_role import ROLE_NAME, ensure_sftp_db_role

# Кавычка и двоеточие — пароль подставляется литералом, без параметров.
_PASSWORD = "test-sftp:pass'word"


@pytest_asyncio.fixture
async def role_session(run_migrations: None) -> AsyncIterator[AsyncSession]:
    owner_url = os.environ["DATABASE_URL"]
    await ensure_sftp_db_role(owner_url, _PASSWORD)
    await ensure_sftp_db_role(owner_url, _PASSWORD)  # повторный запуск не падает
    role_url = make_url(owner_url).set(username=ROLE_NAME, password=_PASSWORD)
    engine = create_async_engine(role_url)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            yield session
    finally:
        await engine.dispose()


class TestAllowed:
    async def test_gateway_queries(self, role_session: AsyncSession) -> None:
        """Записи коммитятся владельцем: роль шлюза видит только зафиксированное."""
        user_id = uuid.uuid4()
        code = f"RR-{uuid.uuid4().hex[:6]}"
        username = f"dev-{uuid.uuid4().hex[:6]}"
        owner = create_async_engine(os.environ["DATABASE_URL"])
        async with owner.begin() as connection:
            await connection.execute(
                sa.insert(User).values(
                    id=user_id,
                    email=f"{user_id}@example.com",
                    os_username=username,
                ),
            )
            await connection.execute(
                sa.insert(Task).values(code=code, title="t", description="d", created_by=user_id),
            )
        try:
            assert (await find_sftp_login(role_session, username=username)) is not None
            assert await list_visible_task_codes(role_session, user_id=user_id) == [code]
            assert await is_task_visible(role_session, user_id=user_id, code=code) is True
            await touch_ssh_key_usage(role_session, user_id=user_id, now=datetime.now(UTC))
        finally:
            async with owner.begin() as connection:
                await connection.execute(sa.delete(Task).where(Task.code == code))
                await connection.execute(sa.delete(User).where(User.id == user_id))
            await owner.dispose()

    async def test_audit_insert(self, role_session: AsyncSession) -> None:
        app_log = AppLog(level=AppLogLevel.INFO, source="sftp-role-test", message="m", context={})
        role_session.add(app_log)
        await role_session.commit()

        owner = create_async_engine(os.environ["DATABASE_URL"])
        async with owner.begin() as connection:
            await connection.execute(sa.delete(AppLog).where(AppLog.source == "sftp-role-test"))
        await owner.dispose()


class TestDenied:
    @pytest.mark.parametrize(
        "statement",
        [
            "SELECT value_encrypted FROM env_variables",
            "SELECT description FROM tasks",
            "UPDATE tasks SET title = 'x'",
            "UPDATE users SET role = 'admin'",
            "SELECT message FROM app_logs",
        ],
        ids=["secrets", "task_text", "task_update", "role_escalation", "read_logs"],
    )
    async def test_statement(self, role_session: AsyncSession, statement: str) -> None:
        with pytest.raises(sa.exc.ProgrammingError, match="permission denied"):
            await role_session.execute(sa.text(statement))
