"""
Запросы учётных данных Git (раздел 3.1 ТЗ) без бизнес-решений и коммита —
их принимает `services/git_credentials.py`.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import sqlalchemy as sa

from db.models.repositories import GitCredential

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

_LOCK_TIMEOUT = "2s"


async def replace_ssh_known_hosts(
    db_session: AsyncSession,
    *,
    credential_id: uuid.UUID,
    previous: str | None,
    known_hosts: str,
) -> bool:
    """
    Compare-and-swap ключей хоста: запись меняется, только если в ней всё ещё
    `previous` — параллельная операция или правка администратора не теряются.
    Строку, заблокированную чужой транзакцией, не ждёт дольше `lock_timeout`.
    """
    await db_session.execute(sa.text(f"SET LOCAL lock_timeout = '{_LOCK_TIMEOUT}'"))
    result = await db_session.execute(
        sa.update(GitCredential)
        .where(
            GitCredential.id == credential_id,
            GitCredential.ssh_known_hosts.is_not_distinct_from(previous),
        )
        .values(ssh_known_hosts=known_hosts),
    )
    return bool(result.rowcount)  # type: ignore[attr-defined]
