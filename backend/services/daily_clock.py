"""
Текущий день «Дейли» (раздел 15.8 ТЗ) по началу дня из системных настроек.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from typing import TYPE_CHECKING

from services.system_settings import get_system_settings
from services.tracker_day import DayWindow, day_bounds

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True, slots=True)
class DailyClock:
    window: DayWindow
    day_start: time

    def bounds(self, day: date) -> tuple[datetime, datetime]:
        return day_bounds(day, self.day_start)


async def load_daily_clock(db_session: AsyncSession, *, now: datetime) -> DailyClock:
    settings = await get_system_settings(db_session)
    return DailyClock(
        window=DayWindow.at(now, settings.day_start_time),
        day_start=settings.day_start_time,
    )
