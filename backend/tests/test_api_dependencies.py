import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_current_user, require_admin
from db.models.enums import UserRole
from db.models.users import User
from services.auth_tokens import issue_session_token
from services.errors import ForbiddenError, UnauthorizedError


async def test_rejects_missing_authorization_header(db_session: AsyncSession) -> None:
    with pytest.raises(UnauthorizedError, match="Не передан токен"):
        await get_current_user(db_session, authorization=None)


async def test_rejects_non_bearer_authorization_header(db_session: AsyncSession) -> None:
    with pytest.raises(UnauthorizedError, match="Не передан токен"):
        await get_current_user(db_session, authorization="Basic abc123")


async def test_rejects_invalid_token(db_session: AsyncSession) -> None:
    with pytest.raises(UnauthorizedError):
        await get_current_user(db_session, authorization="Bearer not-a-real-token")


async def test_rejects_token_for_unknown_user(db_session: AsyncSession) -> None:
    token = issue_session_token(uuid.uuid4())

    with pytest.raises(UnauthorizedError, match="не найден"):
        await get_current_user(db_session, authorization=f"Bearer {token}")


async def test_rejects_token_for_inactive_user(db_session: AsyncSession) -> None:
    user = User(id=uuid.uuid4(), email="inactive@example.com", role=UserRole.USER, is_active=False)
    db_session.add(user)
    await db_session.flush()
    token = issue_session_token(user.id)

    with pytest.raises(UnauthorizedError, match="заблокирован"):
        await get_current_user(db_session, authorization=f"Bearer {token}")


async def test_accepts_valid_token_for_active_user(db_session: AsyncSession) -> None:
    user = User(id=uuid.uuid4(), email="active@example.com", role=UserRole.USER, is_active=True)
    db_session.add(user)
    await db_session.flush()
    token = issue_session_token(user.id)

    resolved = await get_current_user(db_session, authorization=f"Bearer {token}")

    assert resolved.id == user.id


async def test_require_admin_rejects_plain_user() -> None:
    user = User(id=uuid.uuid4(), email="user@example.com", role=UserRole.USER, is_active=True)

    with pytest.raises(ForbiddenError, match="admin"):
        await require_admin(user)


async def test_require_admin_accepts_admin_user() -> None:
    admin = User(id=uuid.uuid4(), email="admin@example.com", role=UserRole.ADMIN, is_active=True)

    resolved = await require_admin(admin)

    assert resolved is admin
