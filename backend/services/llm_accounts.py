"""
Статус лимитов LLM-аккаунта (раздел 16.2 ТЗ, `check_llm_account_limits`) и
уникальность его конфигурационной директории (раздел 19.5).

Отдельного API для опроса лимитов у Claude Agent SDK нет, но CLI сам
присылает в поток сессии `RateLimitEvent` со статусом и временем сброса
окна. Воркер передаёт эти события сюда, а периодическая задача возвращает
аккаунт в `active`, когда окно лимита истекло.
"""

from __future__ import annotations

import os
import posixpath
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import sqlalchemy as sa

from app_logging.config import get_logger
from db.models.enums import LlmAccountStatus
from db.models.llm import LlmAccount
from services.errors import ConflictError, ValidationError

if TYPE_CHECKING:
    from claude_agent_sdk import RateLimitInfo
    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger("llm_accounts")

_REJECTED = "rejected"
_ACCOUNTS_ROOT_ENV_VAR = "CLAUDE_ACCOUNTS_ROOT"
# Volume `claude_accounts` в контейнере worker (docker-compose.yml).
DEFAULT_ACCOUNTS_ROOT = "/data/claude-accounts"


async def record_rate_limit(
    db_session: AsyncSession,
    *,
    account_id: uuid.UUID,
    info: RateLimitInfo,
) -> None:
    """
    `rejected` — аккаунт упёрся в лимит до `resets_at`; иначе — снова `active`.

    Аккаунт, отключённый администратором (`disabled`), не трогается.
    """
    account = await db_session.get(LlmAccount, account_id)
    if account is None or account.status is LlmAccountStatus.DISABLED:
        return
    if info.status == _REJECTED:
        account.status = LlmAccountStatus.RATE_LIMITED
        account.rate_limit_resets_at = (
            datetime.fromtimestamp(info.resets_at, tz=UTC) if info.resets_at else None
        )
    else:
        account.status = LlmAccountStatus.ACTIVE
        account.rate_limit_resets_at = None
    await db_session.commit()
    logger.info(
        "llm_account_rate_limit_recorded",
        account_id=str(account_id),
        status=account.status.value,
        resets_at=account.rate_limit_resets_at,
    )


async def restore_expired_rate_limits(
    db_session: AsyncSession,
    *,
    now: datetime,
) -> list[uuid.UUID]:
    """Периодическая часть: окно лимита истекло — аккаунт снова `active`."""
    stmt = (
        sa.update(LlmAccount)
        .where(
            LlmAccount.status == LlmAccountStatus.RATE_LIMITED,
            LlmAccount.rate_limit_resets_at.is_not(None),
            LlmAccount.rate_limit_resets_at <= now,
        )
        .values(status=LlmAccountStatus.ACTIVE, rate_limit_resets_at=None)
        .returning(LlmAccount.id)
    )
    restored = list((await db_session.execute(stmt)).scalars().all())
    await db_session.commit()
    if restored:
        logger.info("llm_account_rate_limits_restored", account_ids=[str(i) for i in restored])
    return restored


def accounts_root() -> str:
    return posixpath.normpath(os.environ.get(_ACCOUNTS_ROOT_ENV_VAR, DEFAULT_ACCOUNTS_ROOT))


def _overlaps(path: str, other: str) -> bool:
    return path == other or path.startswith(f"{other}/") or other.startswith(f"{path}/")


async def validated_config_dir(
    db_session: AsyncSession,
    claude_config_dir: str,
    *,
    exclude_account_id: uuid.UUID | None = None,
) -> str:
    """
    Раздел 19.5: каталог аккаунта — внутри корня ``CLAUDE_ACCOUNTS_ROOT`` и не
    пересекается с каталогами других аккаунтов. Путь нормализуется, иначе
    `/a/.claude/` и `/a//.claude` обходили бы сравнение. Возвращает путь,
    который нужно сохранить.
    """
    root = accounts_root()
    path = posixpath.normpath(claude_config_dir.strip())
    if not path.startswith(f"{root}/"):
        raise ValidationError(f"Каталог конфигурации должен лежать внутри {root}")
    stmt = sa.select(LlmAccount.claude_config_dir)
    if exclude_account_id is not None:
        stmt = stmt.where(LlmAccount.id != exclude_account_id)
    for other in (await db_session.execute(stmt)).scalars():
        if _overlaps(path, posixpath.normpath(other)):
            raise ConflictError(f"Каталог {path} пересекается с каталогом другого LLM-аккаунта")
    return path
