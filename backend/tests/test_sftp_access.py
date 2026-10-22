"""`services/sftp_access.py` — вход и видимость задач в SFTP-шлюзе (раздел 19.2 ТЗ)."""

from __future__ import annotations

import base64
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from db.models.enums import UserRole
from db.models.tasks import Task
from services.sftp_access import (
    find_sftp_login,
    is_task_visible,
    key_matches,
    list_visible_task_codes,
    touch_ssh_key_usage,
)
from tests.factories import SAMPLE_ECDSA_KEY, SAMPLE_ED25519_KEY, make_user

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from db.models.users import User

_ED25519_BLOB = base64.b64decode(SAMPLE_ED25519_KEY.split()[1])


async def _login_user(db_session: AsyncSession, **fields: object) -> User:
    user = await make_user(db_session)
    user.os_username = f"dev-{uuid.uuid4().hex[:6]}"
    user.ssh_public_key = SAMPLE_ED25519_KEY
    for name, value in fields.items():
        setattr(user, name, value)
    await db_session.flush()
    return user


async def _task(db_session: AsyncSession, owner_id: uuid.UUID) -> Task:
    task = Task(code=f"RR-{uuid.uuid4().hex[:6]}", title="t", description="d", created_by=owner_id)
    db_session.add(task)
    await db_session.flush()
    return task


class TestLogin:
    async def test_finds_by_os_username(self, db_session: AsyncSession) -> None:
        user = await _login_user(db_session)
        assert user.os_username is not None

        assert await find_sftp_login(db_session, username=user.os_username) is user
        assert await find_sftp_login(db_session, username="nobody") is None

    async def test_matching_key(self, db_session: AsyncSession) -> None:
        user = await _login_user(db_session)

        assert key_matches(user, _ED25519_BLOB) is True

    @pytest.mark.parametrize(
        "fields",
        [
            {"ssh_public_key": SAMPLE_ECDSA_KEY},
            {"is_active": False},
            {"ssh_public_key": None},
            {"ssh_public_key": "ssh-ed25519 broken"},
        ],
        ids=["other_key", "inactive", "no_key", "corrupted_key"],
    )
    async def test_rejected(self, db_session: AsyncSession, fields: dict[str, object]) -> None:
        user = await _login_user(db_session, **fields)

        assert key_matches(user, _ED25519_BLOB) is False

    async def test_touch_usage(self, db_session: AsyncSession) -> None:
        user = await _login_user(db_session)
        now = datetime(2026, 10, 22, 12, 0, tzinfo=UTC)

        await touch_ssh_key_usage(db_session, user_id=user.id, now=now)

        await db_session.refresh(user)
        assert user.ssh_key_last_used_at == now


class TestVisibility:
    async def test_user_sees_own(self, db_session: AsyncSession) -> None:
        user = await _login_user(db_session)
        other = await make_user(db_session)
        own = await _task(db_session, user.id)
        foreign = await _task(db_session, other.id)

        codes = await list_visible_task_codes(db_session, user_id=user.id)

        assert own.code in codes
        assert foreign.code not in codes
        assert await is_task_visible(db_session, user_id=user.id, code=own.code) is True
        assert await is_task_visible(db_session, user_id=user.id, code=foreign.code) is False

    async def test_admin_sees_all(self, db_session: AsyncSession) -> None:
        admin = await _login_user(db_session, role=UserRole.ADMIN)
        other = await make_user(db_session)
        foreign = await _task(db_session, other.id)

        assert foreign.code in await list_visible_task_codes(db_session, user_id=admin.id)
        assert await is_task_visible(db_session, user_id=admin.id, code=foreign.code) is True

    async def test_blocked_user_sees_nothing(self, db_session: AsyncSession) -> None:
        user = await _login_user(db_session)
        own = await _task(db_session, user.id)
        user.is_active = False
        await db_session.flush()

        assert await list_visible_task_codes(db_session, user_id=user.id) == []
        assert await is_task_visible(db_session, user_id=user.id, code=own.code) is False
