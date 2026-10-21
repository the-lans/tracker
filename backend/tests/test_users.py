"""`services/users.py` — блокировка по `allowed_emails` и защита администратора (16.2, 19.1)."""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.enums import AppLogLevel, UserRole
from db.models.logs import AppLog
from db.models.users import AllowedEmail, User
from services.errors import ConflictError
from services.users import (
    DEPROVISION_LOG_SOURCE,
    deprovision_inactive_users,
    ensure_allowed_email_deletable,
)


async def _user(
    db_session: AsyncSession,
    *,
    role: UserRole = UserRole.USER,
    allowed: bool = True,
    is_active: bool = True,
    os_username: str | None = None,
) -> User:
    email = f"{uuid.uuid4()}@example.com"
    user = User(email=email, role=role, is_active=is_active, os_username=os_username)
    db_session.add(user)
    if allowed:
        db_session.add(AllowedEmail(email=email))
    await db_session.flush()
    return user


async def _allowed(db_session: AsyncSession, user: User) -> AllowedEmail:
    stmt = sa.select(AllowedEmail).where(AllowedEmail.email == user.email)
    allowed_email: AllowedEmail = (await db_session.execute(stmt)).scalar_one()
    return allowed_email


async def _deprovision_logs(db_session: AsyncSession, user: User) -> list[AppLog]:
    stmt = sa.select(AppLog).where(
        AppLog.source == DEPROVISION_LOG_SOURCE,
        AppLog.context["user_id"].astext == str(user.id),
    )
    return list((await db_session.execute(stmt)).scalars().all())


class TestEnsureAllowedEmailDeletable:
    async def test_last_admin_is_protected(self, db_session: AsyncSession) -> None:
        admin = await _user(db_session, role=UserRole.ADMIN)
        await db_session.execute(
            sa.update(User)
            .where(User.role == UserRole.ADMIN, User.id != admin.id)
            .values(is_active=False),
        )

        with pytest.raises(ConflictError):
            await ensure_allowed_email_deletable(db_session, await _allowed(db_session, admin))

    async def test_admin_with_another_admin(self, db_session: AsyncSession) -> None:
        admin = await _user(db_session, role=UserRole.ADMIN)
        await _user(db_session, role=UserRole.ADMIN)

        await ensure_allowed_email_deletable(db_session, await _allowed(db_session, admin))

    async def test_admin_without_access_ignored(
        self,
        db_session: AsyncSession,
    ) -> None:
        """Второй администратор без email в списке сам будет заблокирован."""
        admin = await _user(db_session, role=UserRole.ADMIN)
        await db_session.execute(
            sa.update(User)
            .where(User.role == UserRole.ADMIN, User.id != admin.id)
            .values(is_active=False),
        )
        await _user(db_session, role=UserRole.ADMIN, allowed=False)

        with pytest.raises(ConflictError):
            await ensure_allowed_email_deletable(db_session, await _allowed(db_session, admin))

    async def test_regular_user(self, db_session: AsyncSession) -> None:
        user = await _user(db_session)

        await ensure_allowed_email_deletable(db_session, await _allowed(db_session, user))

    async def test_email_without_account(self, db_session: AsyncSession) -> None:
        allowed_email = AllowedEmail(email=f"{uuid.uuid4()}@example.com")
        db_session.add(allowed_email)
        await db_session.flush()

        await ensure_allowed_email_deletable(db_session, allowed_email)


class TestDeprovisionInactiveUsers:
    async def test_blocks_removed_and_logs_os_username(self, db_session: AsyncSession) -> None:
        await _user(db_session, role=UserRole.ADMIN)
        removed = await _user(db_session, allowed=False, os_username="dev-removed")
        kept = await _user(db_session)

        deprovisioned = await deprovision_inactive_users(db_session)

        assert removed.id in deprovisioned
        assert kept.id not in deprovisioned
        assert removed.is_active is False
        assert kept.is_active is True
        logs = await _deprovision_logs(db_session, removed)
        assert len(logs) == 1
        assert logs[0].level is AppLogLevel.WARNING
        assert "dev-removed" in logs[0].message
        assert logs[0].context["os_username"] == "dev-removed"

    async def test_idempotent(self, db_session: AsyncSession) -> None:
        await _user(db_session, role=UserRole.ADMIN)
        removed = await _user(db_session, allowed=False)
        await deprovision_inactive_users(db_session)

        again = await deprovision_inactive_users(db_session)

        assert removed.id not in again
        assert len(await _deprovision_logs(db_session, removed)) == 1

    async def test_keeps_last_admin(self, db_session: AsyncSession) -> None:
        await db_session.execute(
            sa.update(User).where(User.role == UserRole.ADMIN).values(is_active=False),
        )
        admin = await _user(db_session, role=UserRole.ADMIN, allowed=False)

        deprovisioned = await deprovision_inactive_users(db_session)

        assert admin.id not in deprovisioned
        assert admin.is_active is True
        logs = await _deprovision_logs(db_session, admin)
        assert [log.level for log in logs] == [AppLogLevel.ERROR]

    async def test_blocks_admin_when_another_remains(self, db_session: AsyncSession) -> None:
        await _user(db_session, role=UserRole.ADMIN)
        removed_admin = await _user(db_session, role=UserRole.ADMIN, allowed=False)

        deprovisioned = await deprovision_inactive_users(db_session)

        assert removed_admin.id in deprovisioned
        assert removed_admin.is_active is False
