"""
Маршрутизация LLM-трафика сессии (раздел 19.7 ТЗ).

Токен сессии: воркер выдаёт случайный токен процессу CLI задачи, шлюз
`llm-gateway` по нему узнаёт задачу; в Redis хранится только sha256 токена.
Маршрут задачи (`llm:route:<task_id>`) — учётка прокси, модель и уровень
рассуждений текущего хода; шлюз подставляет их в каждый запрос сессии.
Оба ключа живут, пока воркер продлевает их вместе с пульсом сессии.

`choose_account` — чистое правило выбора аккаунта задачи по порогам расхода
(пп. 1–5 раздела 19.7); обращение к БД, опросу расхода и уведомлениям — в
`services/account_router.py`.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import uuid
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING

from db.models.enums import LlmAccountStatus, ReasoningEffort
from services.llm_providers import PROVIDERS
from services.session_heartbeat import HEARTBEAT_TTL_SECONDS

if TYPE_CHECKING:
    from redis.asyncio import Redis

    from db.models.llm import LlmAccount

# Раздел 19.7: токен — 256 случайных бит.
_SESSION_TOKEN_BYTES = 32
# Токен и маршрут продлеваются вместе с пульсом сессии (раздел 6.6).
SESSION_TOKEN_TTL_SECONDS = HEARTBEAT_TTL_SECONDS
_SESSION_KEY = "llm:session:{digest}"
_ROUTE_KEY = "llm:route:{task_id}"


class NoLlmAccountAvailableError(Exception):
    """У автора задачи нет ни одного аккаунта, которым можно выполнить ход (п. 5)."""

    message = "Нет доступного LLM-аккаунта"

    def __init__(self) -> None:
        super().__init__(self.message)


@dataclass(frozen=True, slots=True)
class TurnRoute:
    """Чем выполняется ход сессии: учётка прокси, модель и уровень рассуждений."""

    account_id: uuid.UUID
    prefix: str
    model: str
    # Уровень трекера (нода или аккаунт) и уровень, ушедший провайдеру после перевода.
    effort: ReasoningEffort
    provider_effort: ReasoningEffort

    def to_json(self) -> str:
        return json.dumps({**asdict(self), "account_id": str(self.account_id)})

    @classmethod
    def from_json(cls, raw: str | bytes) -> TurnRoute:
        data = json.loads(raw)
        return cls(
            account_id=uuid.UUID(data["account_id"]),
            prefix=data["prefix"],
            model=data["model"],
            effort=ReasoningEffort(data["effort"]),
            provider_effort=ReasoningEffort(data["provider_effort"]),
        )


def _session_key(token: str) -> str:
    return _SESSION_KEY.format(digest=hashlib.sha256(token.encode()).hexdigest())


def _route_key(task_id: uuid.UUID) -> str:
    return _ROUTE_KEY.format(task_id=task_id)


def _text(raw: str | bytes) -> str:
    return raw.decode() if isinstance(raw, bytes) else raw


async def issue_session_token(redis_client: Redis, task_id: uuid.UUID) -> str:
    token = secrets.token_urlsafe(_SESSION_TOKEN_BYTES)
    await redis_client.set(_session_key(token), str(task_id), ex=SESSION_TOKEN_TTL_SECONDS)
    return token


async def renew_session_token(redis_client: Redis, *, task_id: uuid.UUID, token: str) -> None:
    await redis_client.expire(_session_key(token), SESSION_TOKEN_TTL_SECONDS)
    await redis_client.expire(_route_key(task_id), SESSION_TOKEN_TTL_SECONDS)


async def revoke_session_token(redis_client: Redis, *, task_id: uuid.UUID, token: str) -> None:
    await redis_client.delete(_session_key(token), _route_key(task_id))


async def resolve_session_token(redis_client: Redis, token: str) -> uuid.UUID | None:
    """Задача токена; None — неизвестный или просроченный токен (шлюз отвечает 401)."""
    raw = await redis_client.get(_session_key(token))
    return uuid.UUID(_text(raw)) if raw is not None else None


async def publish_route(redis_client: Redis, task_id: uuid.UUID, route: TurnRoute) -> None:
    await redis_client.set(_route_key(task_id), route.to_json(), ex=SESSION_TOKEN_TTL_SECONDS)


async def read_route(redis_client: Redis, task_id: uuid.UUID) -> TurnRoute | None:
    raw = await redis_client.get(_route_key(task_id))
    return TurnRoute.from_json(raw) if raw is not None else None


class SwitchReason(StrEnum):
    """Почему ход выполняется этим аккаунтом (событие `llm_account_switched`)."""

    START = "start"
    KEPT = "kept"
    THRESHOLD_5H = "threshold_5h"
    THRESHOLD_WEEK = "threshold_week"
    RATE_LIMITED = "rate_limited"
    LOGIN_REQUIRED = "login_required"
    DISABLED = "disabled"
    # Прежний аккаунт активен, но не годится для хода: нет модели по умолчанию
    # или провайдер недопустим для ноды `plan_prompt`.
    UNSUITABLE = "unsuitable"
    ALL_ABOVE_THRESHOLD = "all_above_threshold"


_STATUS_REASONS = {
    LlmAccountStatus.RATE_LIMITED: SwitchReason.RATE_LIMITED,
    LlmAccountStatus.LOGIN_REQUIRED: SwitchReason.LOGIN_REQUIRED,
    LlmAccountStatus.DISABLED: SwitchReason.DISABLED,
}


@dataclass(frozen=True, slots=True)
class SwitchThresholds:
    """Пороги автора задачи в процентах (`users.llm_switch_threshold_*_pct`)."""

    five_hour: int
    week: int


@dataclass(frozen=True, slots=True)
class AccountChoice:
    account: LlmAccount
    reason: SwitchReason


def _above(pct: Decimal | None, threshold: int) -> bool:
    # Неизвестный расход (опрос не удался) считается ниже порога.
    return pct is not None and pct >= threshold


def _threshold_reason(account: LlmAccount, thresholds: SwitchThresholds) -> SwitchReason | None:
    if _above(account.usage_5h_pct, thresholds.five_hour):
        return SwitchReason.THRESHOLD_5H
    if _above(account.usage_week_pct, thresholds.week):
        return SwitchReason.THRESHOLD_WEEK
    return None


def _suitable(account: LlmAccount, *, plan_prompt: bool) -> bool:
    provider = PROVIDERS.get(account.provider)
    if provider is None or account.default_model is None:
        return False
    return provider.plan_prompt_allowed or not plan_prompt


def _leave_reason(
    account: LlmAccount,
    thresholds: SwitchThresholds,
    *,
    plan_prompt: bool,
) -> SwitchReason:
    """Почему прежний аккаунт задачи не выполняет этот ход."""
    status_reason = _STATUS_REASONS.get(account.status)
    if status_reason is not None:
        return status_reason
    if not _suitable(account, plan_prompt=plan_prompt):
        return SwitchReason.UNSUITABLE
    return _threshold_reason(account, thresholds) or SwitchReason.UNSUITABLE


def _larger_window(account: LlmAccount) -> Decimal:
    return max(account.usage_5h_pct or Decimal(0), account.usage_week_pct or Decimal(0))


def choose_account(
    accounts: Sequence[LlmAccount],
    *,
    current_id: uuid.UUID | None,
    start_id: uuid.UUID | None,
    thresholds: SwitchThresholds,
    plan_prompt: bool,
) -> AccountChoice:
    """
    Аккаунт хода по пп. 1–5 раздела 19.7. `accounts` — все аккаунты автора
    задачи по `switch_order`; `current_id` — None до первого обращения задачи.
    """
    by_id = {account.id: account for account in accounts}
    candidates = [
        account
        for account in accounts
        if account.status is LlmAccountStatus.ACTIVE and _suitable(account, plan_prompt=plan_prompt)
    ]
    if not candidates:
        raise NoLlmAccountAvailableError
    below = [account for account in candidates if _threshold_reason(account, thresholds) is None]
    previous_id = current_id if current_id is not None else start_id
    previous = by_id.get(previous_id) if previous_id is not None else None
    if previous is not None and previous in below:
        return AccountChoice(previous, SwitchReason.KEPT if current_id else SwitchReason.START)
    if not below:
        # П. 4: работа продолжается до настоящего лимита на наименее израсходованном аккаунте.
        return AccountChoice(min(candidates, key=_larger_window), SwitchReason.ALL_ABOVE_THRESHOLD)
    reason = (
        _leave_reason(previous, thresholds, plan_prompt=plan_prompt)
        if previous is not None
        else SwitchReason.START
    )
    return AccountChoice(below[0], reason)
