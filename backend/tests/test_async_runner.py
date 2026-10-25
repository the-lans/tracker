"""
`tasks/async_runner.py`: Celery-процесс выполняет задачи одну за другой, и
каждая в своём `asyncio.run` — вторая не должна получить соединение пула,
открытое в loop первой.
"""

from __future__ import annotations

import sqlalchemy as sa

from db.session import async_session_factory
from tasks.async_runner import run_with_fresh_pool


async def _select_one() -> int:
    async with async_session_factory() as session:
        return int((await session.execute(sa.text("SELECT 1"))).scalar_one())


class TestRunWithFreshPool:
    def test_consecutive_runs_share_engine(self, run_migrations: None) -> None:
        assert [run_with_fresh_pool(_select_one()) for _ in range(3)] == [1, 1, 1]
