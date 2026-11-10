"""Токен сессии и маршрут хода задачи (раздел 19.7 ТЗ)."""

from __future__ import annotations

import asyncio
import uuid
from typing import TYPE_CHECKING

from db.models.enums import ReasoningEffort
from services.llm_routing import (
    SESSION_TOKEN_TTL_SECONDS,
    TurnRoute,
    issue_session_token,
    llm_session_token,
    publish_route,
    read_route,
    renew_session_token,
    resolve_session_token,
    revoke_session_token,
)

if TYPE_CHECKING:
    from redis.asyncio import Redis


def _route(task_id: uuid.UUID | None = None) -> TurnRoute:
    return TurnRoute(
        account_id=task_id or uuid.uuid4(),
        prefix="acc-0123456789ab",
        model="gpt-6-sol",
        effort=ReasoningEffort.MAX,
        provider_effort=ReasoningEffort.XHIGH,
    )


class TestSessionToken:
    async def test_resolves_to_task(self, redis_client: Redis) -> None:
        task_id = uuid.uuid4()

        token = await issue_session_token(redis_client, task_id)

        assert len(token) >= 43
        assert await resolve_session_token(redis_client, token) == task_id
        assert await redis_client.get(f"llm:session:{token}") is None

    async def test_unknown_token(self, redis_client: Redis) -> None:
        assert await resolve_session_token(redis_client, "forged") is None

    async def test_renew_extends_token_and_route(self, redis_client: Redis) -> None:
        task_id = uuid.uuid4()
        token = await issue_session_token(redis_client, task_id)
        await publish_route(redis_client, task_id, _route())
        await redis_client.expire(f"llm:route:{task_id}", 5)

        await renew_session_token(redis_client, task_id=task_id, token=token)

        assert await redis_client.ttl(f"llm:route:{task_id}") > 5

    async def test_revoke_drops_token_and_route(self, redis_client: Redis) -> None:
        task_id = uuid.uuid4()
        token = await issue_session_token(redis_client, task_id)
        await publish_route(redis_client, task_id, _route())

        await revoke_session_token(redis_client, task_id=task_id, token=token)

        assert await resolve_session_token(redis_client, token) is None
        assert await read_route(redis_client, task_id) is None


class TestSessionTokenScope:
    async def test_renewed_then_revoked(self, redis_client: Redis) -> None:
        task_id = uuid.uuid4()

        async with llm_session_token(redis_client, task_id, interval=0.01) as token:
            await publish_route(redis_client, task_id, _route())
            await redis_client.expire(f"llm:route:{task_id}", 5)
            await asyncio.sleep(0.05)
            assert await redis_client.ttl(f"llm:route:{task_id}") > 5
            assert await resolve_session_token(redis_client, token) == task_id

        assert await resolve_session_token(redis_client, token) is None
        assert await read_route(redis_client, task_id) is None


class TestRoute:
    async def test_round_trip(self, redis_client: Redis) -> None:
        task_id = uuid.uuid4()
        route = _route()

        await publish_route(redis_client, task_id, route)

        assert await read_route(redis_client, task_id) == route
        assert 0 < await redis_client.ttl(f"llm:route:{task_id}") <= SESSION_TOKEN_TTL_SECONDS

    async def test_missing(self, redis_client: Redis) -> None:
        assert await read_route(redis_client, uuid.uuid4()) is None
