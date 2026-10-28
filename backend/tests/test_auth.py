import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.enums import UserRole
from db.models.users import AllowedEmail, User
from services.auth import (
    BLOCKED_USER_MESSAGE,
    NOT_ALLOWED_MESSAGE,
    UNVERIFIED_EMAIL_MESSAGE,
    GoogleIdentity,
    authenticate_or_register,
)
from services.errors import ForbiddenError


class TestLoginRefused:
    """Раздел 19.1: отказ во входе — 403 с причиной для человека."""

    @pytest.mark.parametrize(
        ("email_verified", "existing_active", "message"),
        [
            (False, None, UNVERIFIED_EMAIL_MESSAGE),
            (True, None, NOT_ALLOWED_MESSAGE),
            (True, False, BLOCKED_USER_MESSAGE),
        ],
        ids=["unverified", "not_in_allowlist", "blocked"],
    )
    async def test_reason(
        self,
        db_session: AsyncSession,
        email_verified: bool,
        existing_active: bool | None,
        message: str,
    ) -> None:
        email = f"{uuid.uuid4()}@example.com"
        if existing_active is not None:
            user = User(id=uuid.uuid4(), email=email, role=UserRole.USER, is_active=existing_active)
            db_session.add(user)
            await db_session.flush()

        with pytest.raises(ForbiddenError) as raised:
            await authenticate_or_register(
                db_session,
                identity=GoogleIdentity(email=email, email_verified=email_verified),
            )

        assert raised.value.message == message.format(email=email)


async def test_first_registered_user_becomes_admin(db_session: AsyncSession) -> None:
    email = f"{uuid.uuid4()}@example.com"
    db_session.add(AllowedEmail(email=email))
    await db_session.flush()

    user = await authenticate_or_register(
        db_session,
        identity=GoogleIdentity(email=email, email_verified=True),
    )

    assert user.role is UserRole.ADMIN


async def test_second_registered_user_is_plain_user(db_session: AsyncSession) -> None:
    first_email = f"{uuid.uuid4()}@example.com"
    second_email = f"{uuid.uuid4()}@example.com"
    db_session.add_all([AllowedEmail(email=first_email), AllowedEmail(email=second_email)])
    await db_session.flush()
    await authenticate_or_register(
        db_session,
        identity=GoogleIdentity(email=first_email, email_verified=True),
    )

    second_user = await authenticate_or_register(
        db_session,
        identity=GoogleIdentity(email=second_email, email_verified=True),
    )

    assert second_user.role is UserRole.USER


async def test_existing_user_logs_in_even_if_removed_from_allowlist(
    db_session: AsyncSession,
) -> None:
    email = f"{uuid.uuid4()}@example.com"
    existing = User(id=uuid.uuid4(), email=email, role=UserRole.USER, is_active=True)
    db_session.add(existing)
    await db_session.flush()
    # email отсутствует в allowed_emails — но раздел 19.1 требует это только
    # для НОВОЙ регистрации, не для повторного входа.

    user = await authenticate_or_register(
        db_session,
        identity=GoogleIdentity(email=email, email_verified=True),
    )

    assert user.id == existing.id
