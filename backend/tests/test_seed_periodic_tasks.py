"""
`scripts/seed_periodic_tasks.py` (раздел 16.2, 20.2 п. 8 ТЗ): заполнение
`periodic_tasks` при установке, до первого входа администратора.

Скрипт коммитит своей сессией (`async_session_factory`), поэтому записи
удаляются вручную, как в `test_access.py::TestAuthorizeTaskStream`: фикстура
`seed` после теста убирает весь сид, а не только проверенные строки.
"""

from __future__ import annotations

import importlib.util
from collections.abc import AsyncIterator
from pathlib import Path
from types import ModuleType

import pytest
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


@pytest.fixture
async def seed(run_migrations: None) -> AsyncIterator[ModuleType]:
    module = _load_seed_module()
    try:
        yield module
    finally:
        names = [entry[0] for entry in module._SEED_TASKS]
        async with async_session_factory() as session:
            await session.execute(sa.delete(PeriodicTask).where(PeriodicTask.name.in_(names)))
            await session.commit()


class TestSeed:
    async def test_creates_system_rows_idempotently(self, seed: ModuleType) -> None:
        names = [entry[0] for entry in seed._SEED_TASKS]
        await seed._seed()
        await seed._seed()

        rows = await _seeded_rows(names)
        assert sorted(row.name for row in rows) == sorted(names)
        assert all(row.updated_by is None for row in rows)

    async def test_queue_workers(self, seed: ModuleType) -> None:
        """Раздел 16.2: дневной воркер — каждые 5 минут, ночной — по началу окна (UTC)."""
        names = ["dispatch_ready_tasks", "dispatch_night_tasks"]
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


class TestBackupSchedules:
    async def test_moscow_night(self, seed: ModuleType) -> None:
        """Раздел 20.4: бэкап — 03:00 МСК ежедневно, проверка — вс 02:00 МСК (crontab по UTC)."""
        names = ["backup_to_s3", "verify_s3_backup"]
        await seed._seed()

        rows = {row.name: row for row in await _seeded_rows(names)}
        assert {name: row.crontab_expression for name, row in rows.items()} == {
            "backup_to_s3": "0 0 * * *",
            "verify_s3_backup": "0 23 * * 6",
        }
        assert {row.schedule_type for row in rows.values()} == {PeriodicScheduleType.CRONTAB}
        assert rows["backup_to_s3"].task_path == "tasks.periodic.backup_to_s3"

    @pytest.mark.parametrize(
        ("names", "interval_seconds"),
        [
            (
                [
                    "archive_finished_tasks",
                    "cleanup_finished_task_repositories",
                    "cleanup_archived_task_sessions",
                    "cleanup_archived_task_artifacts",
                ],
                3600,
            ),
            (["purge_old_app_logs"], 86400),
        ],
        ids=["hourly", "daily"],
    )
    async def test_retention_tasks(
        self,
        seed: ModuleType,
        names: list[str],
        interval_seconds: int,
    ) -> None:
        """Разделы 14.2, 14.3, 17.2: сроки архивации и хранения данных проверяются по расписанию."""
        await seed._seed()

        rows = await _seeded_rows(names)
        assert {
            (row.name, row.interval_seconds, row.schedule_type, row.task_path) for row in rows
        } == {
            (name, interval_seconds, PeriodicScheduleType.INTERVAL, f"tasks.periodic.{name}")
            for name in names
        }
