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

from db.models.enums import PeriodicScheduleType
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

    async def test_queue_workers(self, run_migrations: None) -> None:
        """Раздел 16.2: дневной воркер — каждые 5 минут, ночной — по началу окна (UTC)."""
        seed = _load_seed_module()
        names = ["dispatch_ready_tasks", "dispatch_night_tasks"]
        try:
            await seed._seed()

            rows = {row.name: row for row in await _seeded_rows(names)}
            assert (
                rows["dispatch_ready_tasks"].interval_seconds,
                rows["dispatch_ready_tasks"].schedule_type,
            ) == (
                300,
                PeriodicScheduleType.INTERVAL,
            )
            assert (
                rows["dispatch_night_tasks"].crontab_expression,
                rows["dispatch_night_tasks"].schedule_type,
            ) == (
                "15 0 * * *",
                PeriodicScheduleType.CRONTAB,
            )
        finally:
            async with async_session_factory() as session:
                await session.execute(sa.delete(PeriodicTask).where(PeriodicTask.name.in_(names)))
                await session.commit()


class TestBackupSchedules:
    async def test_moscow_night(self, run_migrations: None) -> None:
        """Раздел 20.4: бэкап — 03:00 МСК ежедневно, проверка — вс 02:00 МСК (crontab по UTC)."""
        seed = _load_seed_module()
        names = ["backup_to_s3", "verify_s3_backup"]
        try:
            await seed._seed()

            rows = {row.name: row for row in await _seeded_rows(names)}
            assert {name: row.crontab_expression for name, row in rows.items()} == {
                "backup_to_s3": "0 0 * * *",
                "verify_s3_backup": "0 23 * * 6",
            }
            assert {row.schedule_type for row in rows.values()} == {PeriodicScheduleType.CRONTAB}
            assert rows["backup_to_s3"].task_path == "tasks.periodic.backup_to_s3"
        finally:
            async with async_session_factory() as session:
                await session.execute(sa.delete(PeriodicTask).where(PeriodicTask.name.in_(names)))
                await session.commit()
