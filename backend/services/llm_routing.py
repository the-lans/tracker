"""
Маршрутизация LLM-трафика сессии (раздел 19.7 ТЗ).

Токен сессии: воркер выдаёт случайный токен процессу CLI задачи, шлюз
`llm-gateway` по нему узнаёт задачу; в Redis хранится только sha256 токена.
Маршрут задачи (`llm:route:<task_id>`) — учётка прокси, модель и уровень
рассуждений текущего хода; шлюз подставляет их в каждый запрос сессии.
Оба ключа живут, пока воркер продлевает их вместе с пульсом сессии.

Правило выбора аккаунта хода — `services/llm_account_choice.py`, обращение к
БД, опросу расхода и уведомлениям — `services/account_router.py`.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import secrets
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING

from redis.exceptions import RedisError

from app_logging.config import get_logger
from db.models.enums import LlmSwitchReason, ReasoningEffort
from services.session_heartbeat import HEARTBEAT_INTERVAL_SECONDS, HEARTBEAT_TTL_SECONDS

if TYPE_CHECKING:
    from redis.asyncio import Redis


logger = get_logger("llm_routing")

# Раздел 19.7: токен — 256 случайных бит.
_SESSION_TOKEN_BYTES = 32
# Токен и маршрут продлеваются вместе с пульсом сессии (раздел 6.6).
SESSION_TOKEN_TTL_SECONDS = HEARTBEAT_TTL_SECONDS
_SESSION_KEY = "llm:session:{digest}"
_ROUTE_KEY = "llm:route:{task_id}"


@dataclass(frozen=True, slots=True)
class TurnRoute:
    """Чем выполняется ход сессии: учётка прокси, модель и уровень рассуждений."""

    account_id: uuid.UUID
    prefix: str
    model: str
    # Уровень трекера (нода или аккаунт) и уровень, ушедший провайдеру после перевода.
    effort: ReasoningEffort
    provider_effort: ReasoningEffort
    # Почему аккаунт сменился по сравнению с прежним обращением; None — не сменился.
    switch_reason: LlmSwitchReason | None = None
    # Перед ходом контекст сессии сжат командой `/compact` (смена аккаунта).
    context_compacted: bool = False

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
            switch_reason=_optional_reason(data.get("switch_reason")),
        )


@dataclass(frozen=True, slots=True)
class TurnPlan:
    """
    Маршрут хода и маршрут сжатия контекста перед ним (раздел 19.7, «Сжатие
    контекста»): `/compact` выполняется на ``compact_with`` — прежнем
    аккаунте или, если он недоступен, на новом; None — сжатие не нужно.
    """

    route: TurnRoute
    compact_with: TurnRoute | None = None


def _optional_reason(raw: str | None) -> LlmSwitchReason | None:
    return LlmSwitchReason(raw) if raw is not None else None


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


async def _keep_renewing(
    redis_client: Redis,
    *,
    task_id: uuid.UUID,
    token: str,
    interval: float,
) -> None:
    while True:
        await asyncio.sleep(interval)
        try:
            await renew_session_token(redis_client, task_id=task_id, token=token)
        except RedisError:
            # Пропуск одного продления не страшен: TTL покрывает три интервала.
            logger.warning("llm_session_token_renew_failed", task_id=str(task_id))


@asynccontextmanager
async def llm_session_token(
    redis_client: Redis,
    task_id: uuid.UUID,
    *,
    interval: float = HEARTBEAT_INTERVAL_SECONDS,
) -> AsyncIterator[str]:
    """Токен сессии на время работы воркера с задачей; по выходе отзывается вместе с маршрутом."""
    token = await issue_session_token(redis_client, task_id)
    renewing = asyncio.create_task(
        _keep_renewing(redis_client, task_id=task_id, token=token, interval=interval),
    )
    try:
        yield token
    finally:
        renewing.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await renewing
        with contextlib.suppress(RedisError):
            await revoke_session_token(redis_client, task_id=task_id, token=token)


async def resolve_session_token(redis_client: Redis, token: str) -> uuid.UUID | None:
    """Задача токена; None — неизвестный или просроченный токен (шлюз отвечает 401)."""
    raw = await redis_client.get(_session_key(token))
    return uuid.UUID(_text(raw)) if raw is not None else None


async def publish_route(redis_client: Redis, task_id: uuid.UUID, route: TurnRoute) -> None:
    await redis_client.set(_route_key(task_id), route.to_json(), ex=SESSION_TOKEN_TTL_SECONDS)


async def read_route(redis_client: Redis, task_id: uuid.UUID) -> TurnRoute | None:
    raw = await redis_client.get(_route_key(task_id))
    return TurnRoute.from_json(raw) if raw is not None else None
