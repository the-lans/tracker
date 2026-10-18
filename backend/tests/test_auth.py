import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.enums import UserRole
from db.models.users import AllowedEmail, User
from services.auth import GoogleIdentity, authenticate_or_register
from services.errors import ValidationError


async def test_rejects_unverified_email(db_session: AsyncSession) -> None:
    identity = GoogleIdentity(email="new@example.com", email_verified=False)

    with pytest.raises(ValidationError, match="не подтверждён"):
        await authenticate_or_register(db_session, identity=identity)


async def test_rejects_email_not_in_allowlist(db_session: AsyncSession) -> None:
    identity = GoogleIdentity(email="stranger@example.com", email_verified=True)

    with pytest.raises(ValidationError, match="allowed_emails"):
        await authenticate_or_register(db_session, identity=identity)


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


async def test_inactive_existing_user_is_rejected(db_session: AsyncSession) -> None:
    email = f"{uuid.uuid4()}@example.com"
    db_session.add(User(id=uuid.uuid4(), email=email, role=UserRole.USER, is_active=False))
    await db_session.flush()

    with pytest.raises(ValidationError, match="заблокирована"):
        await authenticate_or_register(
            db_session,
            identity=GoogleIdentity(email=email, email_verified=True),
        )
