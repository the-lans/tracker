"""Общие метрики восстановления для всех процессов воркера."""

import asyncio
from bisect import bisect_left
from dataclasses import dataclass
from typing import Literal

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app_logging.config import get_logger

RecoveryOutcome = Literal["ready", "not_ready", "docker_timeout", "docker_error"]
_OUTCOMES: tuple[RecoveryOutcome, ...] = ("ready", "not_ready", "docker_timeout", "docker_error")
_BOUNDS_MS = (100, 500, 1_000, 5_000, 15_000, 30_000, 60_000)
_KEY = "metrics:paused-session-recovery:v1"
_WRITE_TIMEOUT_SECONDS = 1.0
logger = get_logger("session_recovery_metrics")


@dataclass(frozen=True, slots=True)
class RecoveryMetrics:
    attempts: dict[RecoveryOutcome, int]
    ready_bucket_bounds_ms: tuple[int, ...]
    ready_bucket_counts: list[int]


async def record_recovery(redis: Redis, outcome: RecoveryOutcome, duration_ms: int) -> None:
    try:
        async with asyncio.timeout(_WRITE_TIMEOUT_SECONDS), redis.pipeline() as pipe:
            pipe.hincrby(_KEY, outcome, 1)
            if outcome == "ready":
                pipe.hincrby(_KEY, f"bucket:{bisect_left(_BOUNDS_MS, duration_ms)}", 1)
            await pipe.execute()
    except (TimeoutError, RedisError):
        logger.warning("session_recovery_metrics_write_failed", outcome=outcome)


async def read_recovery_metrics(redis: Redis) -> RecoveryMetrics:
    fields = (*_OUTCOMES, *(f"bucket:{index}" for index in range(len(_BOUNDS_MS) + 1)))
    values = [int(value or 0) for value in await redis.hmget(_KEY, fields)]
    return RecoveryMetrics(
        attempts=dict(zip(_OUTCOMES, values[: len(_OUTCOMES)], strict=True)),
        ready_bucket_bounds_ms=_BOUNDS_MS,
        ready_bucket_counts=values[len(_OUTCOMES) :],
    )
