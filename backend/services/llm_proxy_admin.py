"""
Состояние LLM-прокси для администратора (раздел 15.5 ТЗ): доступность
management API, установленная и последняя выпущенная версия, все учётки
прокси с владельцем и расходом окон, обновление токена, снятие паузы и
удаление учётки без аккаунта трекера. Конфигурацию прокси трекер не меняет.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

import sqlalchemy as sa

from app_logging.config import get_logger
from clients.cliproxy import Credential
from db.models.enums import LlmAccountStatus
from db.models.llm import LlmAccount
from db.models.users import User
from services.errors import ConflictError, ExternalServiceError, NotFoundError

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from clients.cliproxy import CliproxyManagementClient

logger = get_logger("llm_proxy_admin")

_VERSION_ENV_VAR = "CLIPROXY_VERSION"
_UNKNOWN_VERSION = "unknown"


@dataclass(frozen=True, slots=True)
class ProxyCredentialView:
    name: str
    provider: str
    disabled: bool
    requires_sign_in: bool
    quota_blocked: bool
    status: str | None
    # Аккаунт трекера, к которому привязана учётка; None — «без владельца».
    account_id: uuid.UUID | None
    account_label: str | None
    account_status: LlmAccountStatus | None
    owner_email: str | None
    usage_5h_pct: Decimal | None
    usage_week_pct: Decimal | None


@dataclass(frozen=True, slots=True)
class ProxyState:
    available: bool
    error: str | None
    version: str
    latest_version: str | None
    credentials: list[ProxyCredentialView]


def installed_version() -> str:
    """Версия, закреплённая при сборке прокси (`CLIPROXY_VERSION`, раздел 20.2)."""
    return os.environ.get(_VERSION_ENV_VAR) or _UNKNOWN_VERSION


async def _bound_accounts(db_session: AsyncSession) -> dict[str, tuple[LlmAccount, str]]:
    stmt = (
        sa.select(LlmAccount, User.email)
        .join(User, User.id == LlmAccount.created_by)
        .where(LlmAccount.cliproxy_credential.is_not(None))
    )
    rows = (await db_session.execute(stmt)).all()
    return {str(account.cliproxy_credential): (account, email) for account, email in rows}


def _view(credential: Credential, bound: tuple[LlmAccount, str] | None) -> ProxyCredentialView:
    account, email = bound if bound is not None else (None, None)
    return ProxyCredentialView(
        name=credential.name,
        provider=credential.provider,
        disabled=credential.disabled,
        requires_sign_in=credential.requires_sign_in,
        quota_blocked=credential.quota_blocked,
        status=credential.status,
        account_id=account.id if account else None,
        account_label=account.label if account else None,
        account_status=account.status if account else None,
        owner_email=email,
        usage_5h_pct=account.usage_5h_pct if account else None,
        usage_week_pct=account.usage_week_pct if account else None,
    )


async def _latest_version(cliproxy: CliproxyManagementClient) -> str | None:
    """Последняя версия прокси узнаёт с GitHub — её недоступность не мешает остальному."""
    try:
        return await cliproxy.latest_version()
    except ExternalServiceError as exc:
        logger.info("cliproxy_latest_version_unavailable", error=str(exc))
        return None


async def proxy_state(db_session: AsyncSession, cliproxy: CliproxyManagementClient) -> ProxyState:
    """Недоступный прокси — `available=False` с причиной, а не ошибка запроса."""
    try:
        credentials = await cliproxy.list_credentials()
    except ExternalServiceError as exc:
        return ProxyState(
            available=False,
            error=exc.message,
            version=installed_version(),
            latest_version=None,
            credentials=[],
        )
    bound = await _bound_accounts(db_session)
    return ProxyState(
        available=True,
        error=None,
        version=installed_version(),
        latest_version=await _latest_version(cliproxy),
        credentials=[_view(credential, bound.get(credential.name)) for credential in credentials],
    )


async def _credential(cliproxy: CliproxyManagementClient, name: str) -> Credential:
    for credential in await cliproxy.list_credentials():
        if credential.name == name:
            return credential
    raise NotFoundError("Учётки с таким именем в LLM-прокси нет")


async def refresh_credential(cliproxy: CliproxyManagementClient, name: str) -> None:
    credential = await _credential(cliproxy, name)
    await cliproxy.refresh_credential(name)
    logger.info("cliproxy_credential_refreshed", auth_index=credential.auth_index)


async def reset_cooldown(cliproxy: CliproxyManagementClient, name: str) -> None:
    credential = await _credential(cliproxy, name)
    await cliproxy.reset_cooldown(credential.auth_index)
    logger.info("cliproxy_cooldown_reset", auth_index=credential.auth_index)


async def delete_orphan_credential(
    db_session: AsyncSession,
    cliproxy: CliproxyManagementClient,
    name: str,
) -> None:
    """Удалить отсюда можно только учётку без аккаунта: аккаунт удаляется на своей странице."""
    credential = await _credential(cliproxy, name)
    bound = sa.select(LlmAccount.id).where(LlmAccount.cliproxy_credential == name)
    if await db_session.scalar(bound) is not None:
        raise ConflictError("Учётка привязана к LLM-аккаунту — удалите сам аккаунт")
    await cliproxy.delete_credential(name)
    logger.info("cliproxy_orphan_credential_deleted", auth_index=credential.auth_index)
