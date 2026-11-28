"""
Ворота каждого запроса CI-агента и общий резерв лимита в Redis.
"""

from __future__ import annotations

import uuid

from redis.asyncio import Redis

CI_KEY_TTL_SECONDS = 120
CI_GATE_WAIT_SECONDS = 60
CI_GATE_POLL_SECONDS = 1
CI_GATE_READY = "ok"
CI_REPLY_KEY = "llm:ci:reply:{nonce}"


def gate_key(run_id: uuid.UUID) -> str:
    return f"llm:ci:gate:{run_id}"


def request_key(run_id: uuid.UUID) -> str:
    return f"llm:ci:requests:{run_id}"


def reservation_key(owner_id: uuid.UUID, run_id: uuid.UUID) -> str:
    return f"llm:ci:reserve:{owner_id}:{run_id}"


async def reservations(
    redis: Redis,
    owner_id: uuid.UUID,
    *,
    exclude: uuid.UUID | None = None,
) -> dict[uuid.UUID, int]:
    keys = [key async for key in redis.scan_iter(match=f"llm:ci:reserve:{owner_id}:*")]
    counts: dict[uuid.UUID, int] = {}
    for key in keys:
        text = key.decode() if isinstance(key, bytes) else key
        if exclude is not None and text == reservation_key(owner_id, exclude):
            continue
        value = await redis.get(key)
        if value:
            account_id = uuid.UUID(value.decode() if isinstance(value, bytes) else value)
            counts[account_id] = counts.get(account_id, 0) + 1
    return counts


async def request_turn(redis: Redis, run_id: uuid.UUID) -> None:
    nonce = uuid.uuid4().hex
    reply = CI_REPLY_KEY.format(nonce=nonce)
    await redis.rpush(request_key(run_id), nonce)
    await redis.expire(request_key(run_id), CI_KEY_TTL_SECONDS)
    try:
        result = await redis.blpop(reply, timeout=CI_GATE_WAIT_SECONDS)
        if result is None:
            raise RuntimeError("CI-агент не подтвердил проверку лимита")
        raw = result[1]
        message = raw.decode() if isinstance(raw, bytes) else raw
        if message != CI_GATE_READY:
            raise RuntimeError(message)
    finally:
        await redis.delete(reply)
