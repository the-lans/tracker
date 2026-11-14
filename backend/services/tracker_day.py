"""
День трекера (разделы 14.4, 15.8 ТЗ): время трекера — московское, а день D
длится от `system_settings.day_start_time` дня D до того же времени дня D+1.
Отметка задачи или событие в 07:30 при начале дня в 08:00 относится к
предыдущему дню.

«Дейли» показывает завтра, сегодня и `HISTORY_PAST_DAYS` прошлых дней;
отметки задач ставятся только на сегодня и завтра.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from services.errors import ValidationError

# Ночное окно, начало дня и расписания по Москве (без перехода на летнее время).
TRACKER_TIMEZONE = ZoneInfo("Europe/Moscow")
# Раздел 15.8: вкладка «История» — 7 дней до сегодняшнего.
HISTORY_PAST_DAYS = 7
ONE_DAY = timedelta(days=1)

_OUT_OF_HISTORY = "Доступны только дни «Истории»: завтра, сегодня и 7 прошлых дней"
_NOT_MARKABLE = "Задачу можно отметить только на сегодня или на завтра"


def day_of(moment: datetime, day_start: time) -> date:
    """День трекера, к которому относится момент `moment`."""
    local = moment.astimezone(TRACKER_TIMEZONE)
    if local.time().replace(tzinfo=None) < day_start:
        return local.date() - ONE_DAY
    return local.date()


def day_bounds(day: date, day_start: time) -> tuple[datetime, datetime]:
    """Начало (включительно) и конец (исключительно) дня трекера в UTC."""
    start = datetime.combine(day, day_start, tzinfo=TRACKER_TIMEZONE)
    end = datetime.combine(day + ONE_DAY, day_start, tzinfo=TRACKER_TIMEZONE)
    return start.astimezone(UTC), end.astimezone(UTC)


def moment_in_day(day: date, at: time, day_start: time) -> datetime:
    """
    Момент времени `at` внутри дня трекера `day`: время раньше начала дня
    приходится на следующую календарную дату (02:00 дня D — ночь после D).
    """
    calendar_day = day + ONE_DAY if at < day_start else day
    return datetime.combine(calendar_day, at, tzinfo=TRACKER_TIMEZONE).astimezone(UTC)


def local_time(moment: datetime) -> time:
    """Время момента по часовому поясу трекера."""
    return moment.astimezone(TRACKER_TIMEZONE).time().replace(tzinfo=None)


@dataclass(frozen=True, slots=True)
class DayWindow:
    """Дни «Дейли» относительно сегодняшнего дня трекера."""

    today: date

    @classmethod
    def at(cls, now: datetime, day_start: time) -> DayWindow:
        return cls(today=day_of(now, day_start))

    @property
    def yesterday(self) -> date:
        return self.today - ONE_DAY

    @property
    def tomorrow(self) -> date:
        return self.today + ONE_DAY

    @property
    def first_history_day(self) -> date:
        return self.today - timedelta(days=HISTORY_PAST_DAYS)

    def history_days(self) -> list[date]:
        """Завтра, сегодня и прошлые дни — от новых к старым."""
        return [self.tomorrow - timedelta(days=offset) for offset in range(HISTORY_PAST_DAYS + 2)]

    def contains(self, day: date) -> bool:
        return self.first_history_day <= day <= self.tomorrow

    def markable(self, day: date) -> bool:
        return day in (self.today, self.tomorrow)


def ensure_in_history(window: DayWindow, day: date) -> None:
    """День «Истории» — завтра, сегодня или один из 7 прошлых: события, планы и просмотр дня."""
    if not window.contains(day):
        raise ValidationError(_OUT_OF_HISTORY)


def ensure_markable(window: DayWindow, day: date) -> None:
    if not window.markable(day):
        raise ValidationError(_NOT_MARKABLE)
