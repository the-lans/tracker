import uuid

import pytest
from redis.asyncio import Redis

from services.distributed_lock import (
    LockNotAcquiredError,
    acquire_task_operation_lock,
    lock_key,
)


def test_lock_key_is_namespaced_by_task_and_operation() -> None:
    task_id = uuid.uuid4()
    assert lock_key(task_id, "git_push") == f"lock:{task_id}:git_push"


async def test_acquire_lock_succeeds_when_free(redis_client: Redis) -> None:
    task_id = uuid.uuid4()

    async with acquire_task_operation_lock(redis_client, task_id=task_id, operation="op"):
        assert await redis_client.get(lock_key(task_id, "op")) is not None

    assert await redis_client.get(lock_key(task_id, "op")) is None


async def test_acquire_lock_raises_when_already_held(redis_client: Redis) -> None:
    task_id = uuid.uuid4()

    async with acquire_task_operation_lock(redis_client, task_id=task_id, operation="op"):
        with pytest.raises(LockNotAcquiredError):
            async with acquire_task_operation_lock(redis_client, task_id=task_id, operation="op"):
                pass


async def test_lock_can_be_reacquired_after_release(redis_client: Redis) -> None:
    task_id = uuid.uuid4()

    async with acquire_task_operation_lock(redis_client, task_id=task_id, operation="op"):
        pass

    async with acquire_task_operation_lock(redis_client, task_id=task_id, operation="op"):
        assert await redis_client.get(lock_key(task_id, "op")) is not None


async def test_lock_does_not_release_someone_elses_reacquired_lock(redis_client: Redis) -> None:
    task_id = uuid.uuid4()
    key = lock_key(task_id, "op")

    with pytest.raises(RuntimeError):
        async with acquire_task_operation_lock(redis_client, task_id=task_id, operation="op"):
            # Симулируем истечение TTL и перехват блокировки другим процессом.
            await redis_client.set(key, "someone-elses-token")
            raise RuntimeError("сбой внутри блокировки")

    # "Освобождение" не должно было удалить чужой (пере-)захват.
    assert await redis_client.get(key) == b"someone-elses-token"


async def test_lock_scoped_per_operation_not_shared_across_operations(redis_client: Redis) -> None:
    task_id = uuid.uuid4()

    async with acquire_task_operation_lock(redis_client, task_id=task_id, operation="git_push"):
        async with acquire_task_operation_lock(
            redis_client,
            task_id=task_id,
            operation="manual_queue",
        ):
            pass
