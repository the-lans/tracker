"""
Правила доступа SFTP-шлюза (раздел 19.2, 19.3 ТЗ, решение №18 плана).

Шлюз ничего не копирует из трекера заранее: вход сверяет ключ с
`users.ssh_public_key`, а каждая файловая операция заново проверяет, что
пользователь активен и задача ему видна (`user` — свои, `admin` — все).
Смена ключа, блокировка и новые задачи поэтому действуют сразу.

Роль БД шлюза читает только `users` и `tasks`, обновляет
`users.ssh_key_last_used_at` и добавляет записи в `app_logs`
(`sftp_gateway/db_role.py`).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

import sqlalchemy as sa

from db.models.tasks import Task
from db.models.users import User
from services.access import owner_filter
from services.errors import ValidationError
from services.ssh_keys import parse_public_key

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

# Логин шлюза (`users.os_username`) — в духе логина Linux: его набирают в
# `sftp`/`sshfs`, поэтому без пробелов, заглавных и "@".
SFTP_LOGIN_PATTERN = r"^[a-z_][a-z0-9_-]{0,31}$"


async def find_sftp_login(db_session: AsyncSession, *, username: str) -> User | None:
    """Пользователь с этим логином шлюза (`os_username`), в любом статусе."""
    stmt = sa.select(User).where(User.os_username == username)
    return (await db_session.execute(stmt)).scalar_one_or_none()


def key_matches(user: User, key_blob: bytes) -> bool:
    """Вход разрешён активному пользователю, чей сохранённый ключ совпадает с предъявленным."""
    if not user.is_active or user.ssh_public_key is None:
        return False
    try:
        return parse_public_key(user.ssh_public_key).blob == key_blob
    except ValidationError:
        return False


async def touch_ssh_key_usage(
    db_session: AsyncSession,
    *,
    user_id: uuid.UUID,
    now: datetime,
) -> None:
    """Раздел 16.2: дата последнего входа — для `revoke_stale_sshfs_keys`."""
    await db_session.execute(
        sa.update(User).where(User.id == user_id).values(ssh_key_last_used_at=now),
    )
    await db_session.commit()


async def _active_user(db_session: AsyncSession, user_id: uuid.UUID) -> User | None:
    stmt = sa.select(User).where(User.id == user_id, User.is_active == True)  # noqa: E712
    return (await db_session.execute(stmt)).scalar_one_or_none()


async def list_visible_task_codes(db_session: AsyncSession, *, user_id: uuid.UUID) -> list[str]:
    """Коды задач, видимых пользователю; заблокированному — ни одной."""
    user = await _active_user(db_session, user_id)
    if user is None:
        return []
    stmt = sa.select(Task.code).where(owner_filter(Task.created_by, user)).order_by(Task.code)
    return list((await db_session.execute(stmt)).scalars().all())


async def is_task_visible(db_session: AsyncSession, *, user_id: uuid.UUID, code: str) -> bool:
    user = await _active_user(db_session, user_id)
    if user is None:
        return False
    # Только колонки, доступные роли шлюза (`code`, `created_by`), — не `SELECT *`.
    visible = sa.select(Task.code).where(Task.code == code, owner_filter(Task.created_by, user))
    stmt = sa.select(visible.exists())
    return bool((await db_session.execute(stmt)).scalar())
