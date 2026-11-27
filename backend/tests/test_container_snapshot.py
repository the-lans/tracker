"""Снимок контейнеров: отсутствие данных и сбой Docker не означают пустой список."""

from datetime import UTC, datetime, timedelta

import pytest
from redis.asyncio import Redis
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy.ext.asyncio import AsyncSession

from services import container_monitor
from services.container_monitor import DockerCommandError
from services.container_snapshot import (
    CONTAINERS_KEY,
    ContainerSnapshot,
    read_container_snapshot,
    store_container_snapshot,
)
from services.errors import ServiceUnavailableError


class TestContainerSnapshot:
    @pytest.mark.parametrize("age", [timedelta(0), timedelta(seconds=119)])
    async def test_empty_fresh_snapshot_is_valid(self, redis_client: Redis, age: timedelta) -> None:
        now = datetime.now(UTC)
        snapshot = ContainerSnapshot(measured_at=now - age, containers=[])
        await redis_client.set(CONTAINERS_KEY, snapshot.model_dump_json())
        assert await read_container_snapshot(redis_client, now=now) == []

    @pytest.mark.parametrize("data", [None, "not-json", '{"containers": []}'])
    async def test_missing_or_invalid_is_unavailable(
        self, redis_client: Redis, data: str | None
    ) -> None:
        if data is not None:
            await redis_client.set(CONTAINERS_KEY, data)
        with pytest.raises(ServiceUnavailableError):
            await read_container_snapshot(redis_client, now=datetime.now(UTC))

    @pytest.mark.parametrize("age", [timedelta(minutes=2), timedelta(seconds=-1)])
    async def test_stale_or_future_snapshot_is_unavailable(
        self, redis_client: Redis, age: timedelta
    ) -> None:
        now = datetime.now(UTC)
        snapshot = ContainerSnapshot(measured_at=now - age, containers=[])
        await redis_client.set(CONTAINERS_KEY, snapshot.model_dump_json())
        with pytest.raises(ServiceUnavailableError):
            await read_container_snapshot(redis_client, now=now)

    async def test_failed_refresh_preserves_previous_snapshot(
        self, db_session: AsyncSession, redis_client: Redis, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        previous = ContainerSnapshot(measured_at=datetime.now(UTC), containers=[]).model_dump_json()
        await redis_client.set(CONTAINERS_KEY, previous)

        async def failed(*args: str, check: bool = False) -> str:
            if check:
                raise DockerCommandError("Docker недоступен")
            return ""

        monkeypatch.setattr(container_monitor, "run_docker", failed)
        with pytest.raises(DockerCommandError):
            await store_container_snapshot(db_session, redis_client, now=datetime.now(UTC))
        assert await redis_client.get(CONTAINERS_KEY) == previous.encode()

    async def test_redis_failure_is_unavailable(
        self, monkeypatch: pytest.MonkeyPatch, redis_client: Redis
    ) -> None:
        async def failed(*args: object, **kwargs: object) -> None:
            raise RedisConnectionError("Redis недоступен")

        monkeypatch.setattr(redis_client, "get", failed)
        with pytest.raises(ServiceUnavailableError):
            await read_container_snapshot(redis_client, now=datetime.now(UTC))
