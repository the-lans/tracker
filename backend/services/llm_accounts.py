"""
LLM-аккаунты пользователя (разделы 3.1, 15.1, 19.5 ТЗ): создание, модель по
умолчанию, порядок переключения, включение и удаление вместе с учёткой в
LLM-прокси, а также статус лимита (раздел 16.2, `check_llm_account_limits`).

Окно лимита CLI сам присылает в поток сессии `RateLimitEvent` со статусом и
временем сброса — воркер передаёт эти события сюда, а периодическая задача
возвращает аккаунт в `active`, когда окно истекло. Вход в аккаунт —
`services/llm_account_login.py`.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

import httpx
import sqlalchemy as sa

from app_logging.config import get_logger
from clients.cliproxy import CliproxyRequestError, CliproxyUnavailableError
from db.models.enums import LlmAccountStatus, ReasoningEffort
from db.models.llm import LlmAccount
from services.access import owner_filter
from services.errors import ConflictError, ValidationError
from services.integrity import ACCOUNT_IN_USE, commit_or_conflict, ensure_llm_account_deletable
from services.llm_providers import get_provider

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from clients.cliproxy import CliproxyManagementClient
    from db.models.users import User

logger = get_logger("llm_accounts")

_ORDER_CONFLICT = "Порядок LLM-аккаунтов изменился одновременно — обновите страницу"
_PREFIX_TEMPLATE = "acc-{}"
_PREFIX_ID_LENGTH = 12


def account_prefix(account_id: uuid.UUID) -> str:
    """Префикс учётки аккаунта в прокси (раздел 3.1): `acc-` и 12 hex-символов id."""
    return _PREFIX_TEMPLATE.format(account_id.hex[:_PREFIX_ID_LENGTH])


async def next_switch_order(db_session: AsyncSession, owner_id: uuid.UUID) -> int:
    """Место нового аккаунта — в конце порядка переключения владельца (раздел 15.1)."""
    stmt = sa.select(sa.func.coalesce(sa.func.max(LlmAccount.switch_order), 0)).where(
        LlmAccount.created_by == owner_id,
    )
    return int((await db_session.execute(stmt)).scalar_one()) + 1


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


async def create_account(
    db_session: AsyncSession,
    *,
    owner_id: uuid.UUID,
    label: str,
    provider: str,
) -> LlmAccount:
    """Новый аккаунт — в конце порядка переключения, до входа `login_required`."""
    get_provider(provider)
    account_id = uuid.uuid4()
    account = LlmAccount(
        id=account_id,
        label=label,
        provider=provider,
        cliproxy_prefix=account_prefix(account_id),
        switch_order=await next_switch_order(db_session, owner_id),
        status=LlmAccountStatus.LOGIN_REQUIRED,
        created_by=owner_id,
    )
    db_session.add(account)
    await commit_or_conflict(db_session, message=_ORDER_CONFLICT)
    return account


def _strip_prefix(account: LlmAccount, model_id: str) -> str:
    return model_id.removeprefix(f"{account.cliproxy_prefix}/")


async def account_models(
    cliproxy: CliproxyManagementClient,
    account: LlmAccount,
) -> list[str]:
    """
    Модели учётки аккаунта без префикса, кроме не годных агенту по реестру
    провайдера; до входа список пуст.
    """
    if account.cliproxy_credential is None:
        return []
    provider = get_provider(account.provider)
    models = await cliproxy.credential_models(account.cliproxy_credential)
    stripped = (_strip_prefix(account, model_id) for model_id in models)
    return [model for model in stripped if provider.offers_model(model)]


async def ensure_model_available(
    cliproxy: CliproxyManagementClient,
    account: LlmAccount,
    model: str,
) -> None:
    """Раздел 3.1: модель по умолчанию — из списка моделей учётки, иначе 422."""
    if account.cliproxy_credential is None:
        raise ValidationError("Модель выбирается после входа в аккаунт")
    if model not in await account_models(cliproxy, account):
        raise ValidationError(f"Модели {model} нет у учётки аккаунта")


async def reorder_accounts(
    db_session: AsyncSession,
    *,
    owner_id: uuid.UUID,
    account_ids: list[uuid.UUID],
) -> list[LlmAccount]:
    """Раздел 15.1: новый порядок переключения — все аккаунты владельца по одному разу."""
    accounts = await owned_accounts(db_session, owner_id)
    by_id = {account.id: account for account in accounts}
    if len(account_ids) != len(set(account_ids)) or set(account_ids) != by_id.keys():
        raise ValidationError("Порядок должен перечислять каждый аккаунт владельца один раз")
    for position, account_id in enumerate(account_ids, start=1):
        by_id[account_id].switch_order = position
    await commit_or_conflict(db_session, message=_ORDER_CONFLICT)
    return [by_id[account_id] for account_id in account_ids]


async def owned_accounts(db_session: AsyncSession, owner_id: uuid.UUID) -> list[LlmAccount]:
    """Аккаунты владельца в порядке переключения."""
    stmt = (
        sa.select(LlmAccount)
        .where(LlmAccount.created_by == owner_id)
        .order_by(LlmAccount.switch_order)
    )
    return list((await db_session.execute(stmt)).scalars().all())


async def visible_accounts(db_session: AsyncSession, user: User) -> list[LlmAccount]:
    """Раздел 15.1: свои аккаунты в порядке переключения, у `admin` — все, по владельцам."""
    stmt = (
        sa.select(LlmAccount)
        .where(owner_filter(LlmAccount.created_by, user))
        .order_by(LlmAccount.created_by, LlmAccount.switch_order)
    )
    return list((await db_session.execute(stmt)).scalars().all())


async def update_account(
    db_session: AsyncSession,
    cliproxy: CliproxyManagementClient,
    account: LlmAccount,
    *,
    label: str | None,
    default_model: str | None,
    default_effort: ReasoningEffort | None,
    enabled: bool | None,
    now: datetime,
) -> LlmAccount:
    """
    Правка аккаунта; None — поле не меняется. Модель проверяется по учётке до
    любых изменений (422), включение синхронизируется с прокси (502 — ничего
    не изменено).
    """
    if default_model is not None:
        await ensure_model_available(cliproxy, account, default_model)
        account.default_model = default_model
    if label is not None:
        account.label = label
    if default_effort is not None:
        account.default_effort = default_effort
    if enabled is not None:
        await set_account_enabled(db_session, cliproxy, account, enabled=enabled, now=now)
    await db_session.commit()
    await db_session.refresh(account)
    return account


def _enabled_status(account: LlmAccount, *, now: datetime) -> LlmAccountStatus:
    if account.cliproxy_credential is None:
        return LlmAccountStatus.LOGIN_REQUIRED
    if account.rate_limit_resets_at is not None and account.rate_limit_resets_at > now:
        return LlmAccountStatus.RATE_LIMITED
    return LlmAccountStatus.ACTIVE


async def set_account_enabled(
    db_session: AsyncSession,
    cliproxy: CliproxyManagementClient,
    account: LlmAccount,
    *,
    enabled: bool,
    now: datetime,
) -> None:
    """
    Раздел 19.7: выключенный в трекере аккаунт выключается и в прокси — сначала
    прокси, чтобы при его недоступности (502) статусы не разошлись.
    """
    if (account.status is not LlmAccountStatus.DISABLED) == enabled:
        return
    if account.cliproxy_credential is not None:
        await cliproxy.set_credential_disabled(account.cliproxy_credential, disabled=not enabled)
    account.status = _enabled_status(account, now=now) if enabled else LlmAccountStatus.DISABLED
    await db_session.commit()
    logger.info("llm_account_enabled_changed", account_id=str(account.id), enabled=enabled)


async def delete_account(
    db_session: AsyncSession,
    cliproxy: CliproxyManagementClient,
    account: LlmAccount,
) -> None:
    """
    Раздел 3.2: аккаунт задачи или истории `node_logs` не удаляется (409);
    удаление убирает и учётку в прокси, недоступный прокси — 502.
    """
    await ensure_llm_account_deletable(db_session, account.id)
    credential = account.cliproxy_credential
    await db_session.delete(account)
    try:
        await db_session.flush()
    except sa.exc.IntegrityError as exc:
        await db_session.rollback()
        raise ConflictError(ACCOUNT_IN_USE) from exc
    if credential is not None:
        try:
            await cliproxy.delete_credential(credential)
        except CliproxyRequestError as exc:
            if exc.response_status != httpx.codes.NOT_FOUND:
                await db_session.rollback()
                raise
        except CliproxyUnavailableError:
            await db_session.rollback()
            raise
    await db_session.commit()
    logger.info("llm_account_deleted", account_id=str(account.id))
