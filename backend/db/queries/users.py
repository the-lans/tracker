"""
Запросы пользователей (раздел 3.1 ТЗ) без бизнес-решений и коммита — их
принимает сервис.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import sqlalchemy as sa

from db.models.users import User

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def increment_session_version(db_session: AsyncSession, user_id: uuid.UUID) -> None:
    """Атомарно: параллельные отзывы сессий не теряют друг друга."""
    await db_session.execute(
        sa.update(User).where(User.id == user_id).values(session_version=User.session_version + 1),
    )


async def deactivate_user(db_session: AsyncSession, user_id: uuid.UUID) -> None:
    """Блокировка и отзыв сессий одним UPDATE, без коммита."""
    await db_session.execute(
        sa.update(User)
        .where(User.id == user_id, User.is_active.is_(True))
        .values(is_active=False, session_version=User.session_version + 1)
    )
