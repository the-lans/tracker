"""
Вход в LLM-аккаунт через прокси (раздел 19.5 ТЗ).

Трекер получает у прокси ссылку входа, пользователь входит у провайдера и
вставляет адрес, на который вернулся браузер; прокси обменивает код на
токены и сохраняет учётку у себя. Учётку трекер находит по имени из итога
входа, а если прокси его не вернул (вход Claude) — по разнице списка учёток
до входа и после, под распределённой блокировкой. Найденной учётке
выставляется префикс аккаунта, и запросы к модели с этим префиксом прокси
выполняет только ею (раздел 19.7).

Незавершённый вход хранится в Redis (`llm:login:<account_id>`) и через 10
минут отменяется, в том числе в прокси.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

import sqlalchemy as sa

from app_logging.config import get_logger
from clients.cliproxy import CliproxyRequestError, OAuthState, OAuthStatus
from db.models.enums import LlmAccountStatus
from db.models.llm import LlmAccount
from services.distributed_lock import LockNotAcquiredError, acquire_lock
from services.errors import ConflictError
from services.integrity import commit_or_conflict
from services.llm_providers import get_provider

if TYPE_CHECKING:
    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncSession

    from clients.cliproxy import CliproxyManagementClient

logger = get_logger("llm_account_login")

# Раздел 19.5: незавершённый вход отменяется через 10 минут.
LOGIN_TIMEOUT = timedelta(minutes=10)
# Запись живёт дольше срока входа, чтобы просроченный вход можно было отменить в прокси.
_RECORD_TTL_SECONDS = 30 * 60
_RECORD_KEY = "llm:login:{account_id}"
_DEADLINES_KEY = "llm:login:deadlines"
_BIND_LOCK_KEY = "lock:cliproxy:login"
_BIND_LOCK_TTL_SECONDS = 30

_EXPIRED = "Вход не начат или истёк — начните вход заново"
_TAKEN = "Эта подписка уже подключена к другому LLM-аккаунту"
_NOT_FOUND = "Прокси не создал новую учётку — возможно, подписка уже подключена к другому аккаунту"
_AMBIGUOUS = "Одновременно с этим выполнялся другой вход — начните вход заново"
_BUSY = "Сейчас завершается другой вход — повторите через несколько секунд"


@dataclass(frozen=True, slots=True)
class LoginStart:
    url: str
    state: str


@dataclass(frozen=True, slots=True)
class LoginResult:
    state: OAuthState
    error: str | None = None


@dataclass(frozen=True, slots=True)
class _Record:
    state: str
    deadline: str
    # Учётки провайдера до входа; None — повторный вход в уже привязанную учётку.
    known: list[str] | None


def _record_key(account_id: uuid.UUID) -> str:
    return _RECORD_KEY.format(account_id=account_id)


async def _load(redis_client: Redis, account_id: uuid.UUID) -> _Record | None:
    raw = await redis_client.get(_record_key(account_id))
    if raw is None:
        return None
    return _Record(**json.loads(raw))


async def _drop(redis_client: Redis, account_id: uuid.UUID) -> None:
    await redis_client.delete(_record_key(account_id))
    await redis_client.zrem(_DEADLINES_KEY, str(account_id))


async def _provider_credentials(
    cliproxy: CliproxyManagementClient,
    oauth_provider: str,
) -> set[str]:
    return {
        credential.name
        for credential in await cliproxy.list_credentials()
        if credential.provider == oauth_provider
    }


async def _cancel_in_proxy(cliproxy: CliproxyManagementClient, state: str) -> None:
    try:
        await cliproxy.oauth_cancel(state)
    except CliproxyRequestError:
        # Сессия входа уже завершилась или истекла в прокси — отменять нечего.
        logger.info("llm_login_cancel_skipped")


async def cancel_login(
    redis_client: Redis,
    cliproxy: CliproxyManagementClient,
    account: LlmAccount,
) -> None:
    record = await _load(redis_client, account.id)
    if record is None:
        return
    await _cancel_in_proxy(cliproxy, record.state)
    await _drop(redis_client, account.id)


async def start_login(
    redis_client: Redis,
    cliproxy: CliproxyManagementClient,
    account: LlmAccount,
    *,
    now: datetime,
) -> LoginStart:
    """Ссылка входа; прежний незавершённый вход этого аккаунта отменяется."""
    provider = get_provider(account.provider)
    await cancel_login(redis_client, cliproxy, account)
    known = (
        None
        if account.cliproxy_credential is not None
        else sorted(await _provider_credentials(cliproxy, provider.oauth_provider))
    )
    start = await cliproxy.oauth_auth_url(
        provider=provider.oauth_provider,
        credential=account.cliproxy_credential,
    )
    deadline = now + LOGIN_TIMEOUT
    record = _Record(state=start.state, deadline=deadline.isoformat(), known=known)
    await redis_client.set(
        _record_key(account.id),
        json.dumps(asdict(record)),
        ex=_RECORD_TTL_SECONDS,
    )
    await redis_client.zadd(_DEADLINES_KEY, {str(account.id): deadline.timestamp()})
    logger.info("llm_login_started", account_id=str(account.id), provider=provider.id)
    return LoginStart(url=start.url, state=start.state)


async def _active_record(
    redis_client: Redis,
    cliproxy: CliproxyManagementClient,
    account: LlmAccount,
    *,
    now: datetime,
) -> _Record | None:
    record = await _load(redis_client, account.id)
    if record is None:
        return None
    if datetime.fromisoformat(record.deadline) <= now:
        await _cancel_in_proxy(cliproxy, record.state)
        await _drop(redis_client, account.id)
        return None
    return record


async def submit_login_callback(
    db_session: AsyncSession,
    redis_client: Redis,
    cliproxy: CliproxyManagementClient,
    account: LlmAccount,
    *,
    redirect_url: str,
    now: datetime,
) -> LoginResult:
    """Передаёт прокси адрес возврата из браузера и сразу проверяет итог входа."""
    record = await _active_record(redis_client, cliproxy, account, now=now)
    if record is None:
        return LoginResult(OAuthState.ERROR, _EXPIRED)
    await cliproxy.oauth_callback(
        provider=get_provider(account.provider).oauth_provider,
        state=record.state,
        redirect_url=redirect_url,
    )
    return await _finish(db_session, redis_client, cliproxy, account, record)


async def poll_login(
    db_session: AsyncSession,
    redis_client: Redis,
    cliproxy: CliproxyManagementClient,
    account: LlmAccount,
    *,
    now: datetime,
) -> LoginResult:
    """Итог входа: `wait`, пока прокси не обменял код; при `ok` учётка уже привязана."""
    record = await _active_record(redis_client, cliproxy, account, now=now)
    if record is None:
        return LoginResult(OAuthState.ERROR, _EXPIRED)
    return await _finish(db_session, redis_client, cliproxy, account, record)


async def _finish(
    db_session: AsyncSession,
    redis_client: Redis,
    cliproxy: CliproxyManagementClient,
    account: LlmAccount,
    record: _Record,
) -> LoginResult:
    status = await cliproxy.oauth_status(record.state)
    if status.state is OAuthState.WAIT:
        return LoginResult(OAuthState.WAIT)
    if status.state is OAuthState.ERROR:
        await _drop(redis_client, account.id)
        logger.info("llm_login_failed", account_id=str(account.id))
        return LoginResult(OAuthState.ERROR, status.error)
    try:
        async with acquire_lock(
            redis_client,
            _BIND_LOCK_KEY,
            ttl_seconds=_BIND_LOCK_TTL_SECONDS,
            busy_message=_BUSY,
        ):
            await _bind(db_session, cliproxy, account, record=record, status=status)
    except LockNotAcquiredError as exc:
        raise ConflictError(str(exc)) from exc
    except ConflictError:
        await _drop(redis_client, account.id)
        raise
    await _drop(redis_client, account.id)
    return LoginResult(OAuthState.OK)


async def _new_credential(
    db_session: AsyncSession,
    cliproxy: CliproxyManagementClient,
    account: LlmAccount,
    *,
    record: _Record,
    status: OAuthStatus,
) -> str:
    if status.credential is not None:
        return status.credential
    oauth_provider = get_provider(account.provider).oauth_provider
    bound = set((await db_session.execute(_bound_credentials())).scalars())
    fresh = await _provider_credentials(cliproxy, oauth_provider) - set(record.known or []) - bound
    if not fresh:
        raise ConflictError(_NOT_FOUND)
    if len(fresh) > 1:
        raise ConflictError(_AMBIGUOUS)
    return fresh.pop()


def _bound_credentials() -> sa.Select[str | None]:
    return sa.select(LlmAccount.cliproxy_credential).where(
        LlmAccount.cliproxy_credential.is_not(None),
    )


async def _bind(
    db_session: AsyncSession,
    cliproxy: CliproxyManagementClient,
    account: LlmAccount,
    *,
    record: _Record,
    status: OAuthStatus,
) -> None:
    """Привязывает учётку к аккаунту и выставляет ей префикс; аккаунт снова в работе."""
    if account.cliproxy_credential is not None:
        credential = account.cliproxy_credential
    else:
        credential = await _new_credential(
            db_session,
            cliproxy,
            account,
            record=record,
            status=status,
        )
        taken = sa.select(LlmAccount.id).where(
            LlmAccount.cliproxy_credential == credential,
            LlmAccount.id != account.id,
        )
        if await db_session.scalar(taken) is not None:
            raise ConflictError(_TAKEN)
    await cliproxy.set_credential_prefix(credential, account.cliproxy_prefix)
    account.cliproxy_credential = credential
    if account.status is not LlmAccountStatus.DISABLED:
        account.status = LlmAccountStatus.ACTIVE
    await commit_or_conflict(db_session, message=_TAKEN)
    logger.info("llm_login_completed", account_id=str(account.id))


async def cancel_expired_logins(
    redis_client: Redis,
    cliproxy: CliproxyManagementClient,
    *,
    now: datetime,
) -> int:
    """Периодическая часть: просроченные входы отменяются и в прокси."""
    expired = [
        member.decode() if isinstance(member, bytes) else str(member)
        for member in await redis_client.zrangebyscore(_DEADLINES_KEY, "-inf", now.timestamp())
    ]
    for raw_id in expired:
        account_id = uuid.UUID(raw_id)
        record = await _load(redis_client, account_id)
        if record is not None:
            await _cancel_in_proxy(cliproxy, record.state)
        await _drop(redis_client, account_id)
    return len(expired)
