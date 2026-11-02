"""
Состояние LLM-аккаунтов по данным прокси (разделы 16.2, 19.5, 19.7 ТЗ).

`check_llm_accounts` — тело периодической `check_llm_account_limits`: вернуть
в `active` аккаунты с истёкшим окном лимита, опросить расход окон у
аккаунтов со входом, перевести в `login_required` аккаунты, учётке которых
прокси требует повторного входа (или учётки в прокси больше нет), и
отменить незавершённые входы старше 5 минут. Сбой одного аккаунта не
останавливает остальные.

`require_login` — переход в `login_required` по compare-and-swap статуса с
уведомлением владельца (раздел 18.2); его же вызывает воркер, когда
провайдер отклонил вход посреди хода.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import sqlalchemy as sa

from app_logging.config import get_logger
from db.models.enums import LlmAccountStatus
from db.models.llm import LlmAccount
from services.errors import ExternalServiceError
from services.llm_account_login import cancel_expired_logins
from services.llm_accounts import restore_expired_rate_limits
from services.llm_usage import refresh_account_usage
from services.notifications import NotificationEvent, notify_user_event

if TYPE_CHECKING:
    from datetime import datetime

    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncSession

    from clients.cliproxy import CliproxyManagementClient, Credential

logger = get_logger("llm_account_checks")

# Аккаунты со входом: их расход и вход сверяются с прокси.
_SIGNED_IN_STATUSES = (LlmAccountStatus.ACTIVE, LlmAccountStatus.RATE_LIMITED)


@dataclass(slots=True)
class AccountsCheckResult:
    restored: list[uuid.UUID] = field(default_factory=list)
    polled: list[uuid.UUID] = field(default_factory=list)
    login_required: list[uuid.UUID] = field(default_factory=list)
    cancelled_logins: int = 0


async def require_login(db_session: AsyncSession, account_id: uuid.UUID) -> bool:
    """`active`/`rate_limited` → `login_required`; True — переход выполнен этим вызовом."""
    stmt = (
        sa.update(LlmAccount)
        .where(LlmAccount.id == account_id, LlmAccount.status.in_(_SIGNED_IN_STATUSES))
        .values(status=LlmAccountStatus.LOGIN_REQUIRED)
        .returning(LlmAccount.created_by, LlmAccount.label)
    )
    changed = (await db_session.execute(stmt)).one_or_none()
    await db_session.commit()
    if changed is None:
        return False
    owner_id, label = changed
    logger.info("llm_account_login_required", account_id=str(account_id))
    await notify_user_event(
        db_session,
        event=NotificationEvent.LLM_LOGIN_REQUIRED,
        user_id=owner_id,
        detail=f"Войдите в LLM-аккаунт «{label}» заново",
    )
    return True


async def _signed_in_accounts(db_session: AsyncSession) -> list[LlmAccount]:
    stmt = (
        sa.select(LlmAccount)
        .where(
            LlmAccount.status.in_(_SIGNED_IN_STATUSES),
            LlmAccount.cliproxy_credential.is_not(None),
        )
        .order_by(LlmAccount.created_at, LlmAccount.id)
    )
    return list((await db_session.execute(stmt)).scalars())


async def _check_account(
    db_session: AsyncSession,
    cliproxy: CliproxyManagementClient,
    account: LlmAccount,
    *,
    credential: Credential | None,
    now: datetime,
    result: AccountsCheckResult,
) -> None:
    if credential is None or credential.requires_sign_in:
        if await require_login(db_session, account.id):
            result.login_required.append(account.id)
        return
    snapshot = await refresh_account_usage(
        cliproxy,
        account,
        auth_index=credential.auth_index,
        now=now,
    )
    await db_session.commit()
    if snapshot is not None:
        result.polled.append(account.id)


async def check_llm_accounts(
    db_session: AsyncSession,
    *,
    redis_client: Redis,
    cliproxy: CliproxyManagementClient,
    now: datetime,
) -> AccountsCheckResult:
    result = AccountsCheckResult(restored=await restore_expired_rate_limits(db_session, now=now))
    # Аккаунты — до списка учёток: вход, завершившийся между двумя запросами, в
    # сверку не попадёт, а не окажется «без учётки в прокси».
    accounts = await _signed_in_accounts(db_session)
    try:
        listed = await cliproxy.list_credentials()
    except ExternalServiceError as exc:
        # Без прокси сверять нечего: окна лимита уже восстановлены по времени.
        logger.warning("llm_accounts_check_proxy_unavailable", error=exc.message)
        return result
    credentials = {credential.name: credential for credential in listed}
    for account in accounts:
        await _check_account(
            db_session,
            cliproxy,
            account,
            credential=credentials.get(str(account.cliproxy_credential)),
            now=now,
            result=result,
        )
    result.cancelled_logins = await cancel_expired_logins(redis_client, cliproxy, now=now)
    return result
