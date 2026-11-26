"""После разблокировки отозванные токены не восстанавливаются."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from db.queries.users import deactivate_user
from services.auth import load_session_user
from services.auth_tokens import issue_session_token, verify_session_token
from services.errors import UnauthorizedError
from tests.factories import make_user


class TestSessionDeactivation:
    async def test_block_revokes_once(self, db_session: AsyncSession) -> None:
        user = await make_user(db_session)
        claims = verify_session_token(
            issue_session_token(user.id, session_version=user.session_version)
        )
        previous = user.session_version
        await deactivate_user(db_session, user.id)
        await deactivate_user(db_session, user.id)
        await db_session.commit()
        await db_session.refresh(user)
        assert user.session_version == previous + 1
        assert not user.is_active
        user.is_active = True
        await db_session.commit()
        with pytest.raises(UnauthorizedError, match="Сессия завершена"):
            await load_session_user(db_session, claims)
