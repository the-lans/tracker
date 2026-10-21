"""
`scripts/seed_periodic_tasks.py` (раздел 16.2, 20.2 п. 8 ТЗ): заполнение
`periodic_tasks` при установке, до первого входа администратора.

Скрипт коммитит своей сессией (`async_session_factory`), поэтому записи
удаляются вручную, как в `test_access.py::TestAuthorizeTaskStream`.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import sqlalchemy as sa

from db.models.periodic import PeriodicTask
from db.session import async_session_factory

_SEED_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "seed_periodic_tasks.py"


def _load_seed_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("seed_periodic_tasks", _SEED_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def _seeded_rows(names: list[str]) -> list[PeriodicTask]:
    async with async_session_factory() as session:
        stmt = sa.select(PeriodicTask).where(PeriodicTask.name.in_(names))
        return list((await session.execute(stmt)).scalars().all())


class TestSeed:
    async def test_creates_system_rows_idempotently(self, run_migrations: None) -> None:
        seed = _load_seed_module()
        names = [entry[0] for entry in seed._SEED_TASKS]
        try:
            await seed._seed()
            await seed._seed()

            rows = await _seeded_rows(names)
            assert sorted(row.name for row in rows) == sorted(names)
            assert all(row.updated_by is None for row in rows)
        finally:
            async with async_session_factory() as session:
                await session.execute(sa.delete(PeriodicTask).where(PeriodicTask.name.in_(names)))
                await session.commit()
