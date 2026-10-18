import asyncio
import uuid

from redis.asyncio import Redis

from services.task_signal import channel_name, publish_task_signal, wait_for_task_signal


def test_channel_name_is_namespaced_per_task() -> None:
    task_id = uuid.uuid4()
    assert channel_name(task_id) == f"task:{task_id}:signal"


async def test_wait_for_task_signal_returns_true_when_published(redis_client: Redis) -> None:
    task_id = uuid.uuid4()

    async def _publish_soon() -> None:
        await asyncio.sleep(0.1)
        await publish_task_signal(redis_client, task_id)

    publisher = asyncio.create_task(_publish_soon())
    try:
        received = await wait_for_task_signal(redis_client, task_id, timeout=5.0)
    finally:
        await publisher

    assert received is True


async def test_wait_for_task_signal_with_no_timeout_waits_until_published(
    redis_client: Redis,
) -> None:
    task_id = uuid.uuid4()

    async def _publish_soon() -> None:
        await asyncio.sleep(0.1)
        await publish_task_signal(redis_client, task_id)

    publisher = asyncio.create_task(_publish_soon())
    try:
        received = await wait_for_task_signal(redis_client, task_id, timeout=None)
    finally:
        await publisher

    assert received is True


async def test_wait_for_task_signal_times_out_without_publish(redis_client: Redis) -> None:
    task_id = uuid.uuid4()

    received = await wait_for_task_signal(redis_client, task_id, timeout=0.3)

    assert received is False


async def test_signal_is_scoped_to_its_own_task(redis_client: Redis) -> None:
    task_id = uuid.uuid4()
    other_task_id = uuid.uuid4()

    await publish_task_signal(redis_client, other_task_id)
    received = await wait_for_task_signal(redis_client, task_id, timeout=0.3)

    assert received is False
