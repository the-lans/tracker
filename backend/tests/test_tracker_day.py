"""День трекера «Дейли» (раздел 15.8 ТЗ): границы дня по началу дня и окно «Истории»."""

from __future__ import annotations

from datetime import UTC, date, datetime, time

import pytest

from services.errors import ValidationError
from services.tracker_day import (
    DayWindow,
    day_bounds,
    day_of,
    ensure_markable,
    local_time,
    moment_in_day,
)

_DAY_START = time(8, 0)
_TODAY = date(2026, 11, 16)


class TestDayOf:
    @pytest.mark.parametrize(
        ("moment", "expected"),
        [
            # 08:00 МСК = 05:00 UTC.
            (datetime(2026, 11, 16, 5, 0, tzinfo=UTC), date(2026, 11, 16)),
            (datetime(2026, 11, 16, 4, 59, tzinfo=UTC), date(2026, 11, 15)),
            # 23:30 МСК — тот же день, 02:00 МСК следующей даты — ещё он же.
            (datetime(2026, 11, 16, 20, 30, tzinfo=UTC), date(2026, 11, 16)),
            (datetime(2026, 11, 16, 23, 0, tzinfo=UTC), date(2026, 11, 16)),
        ],
        ids=["начало-дня", "минута-до-начала", "вечер", "ночь-после-полуночи"],
    )
    def test_belongs_to_tracker_day(self, moment: datetime, expected: date) -> None:
        assert day_of(moment, _DAY_START) == expected

    def test_midnight_day_start_is_calendar_day(self) -> None:
        moment = datetime(2026, 11, 15, 21, 0, tzinfo=UTC)  # 00:00 МСК 16.11

        assert day_of(moment, time(0, 0)) == date(2026, 11, 16)


class TestDayBounds:
    def test_from_day_start_to_next(self) -> None:
        assert day_bounds(_TODAY, _DAY_START) == (
            datetime(2026, 11, 16, 5, 0, tzinfo=UTC),
            datetime(2026, 11, 17, 5, 0, tzinfo=UTC),
        )

    @pytest.mark.parametrize(
        ("at", "expected"),
        [
            (time(10, 30), datetime(2026, 11, 16, 7, 30, tzinfo=UTC)),
            # 02:00 дня 16.11 — ночь после него, календарно 17.11.
            (time(2, 0), datetime(2026, 11, 16, 23, 0, tzinfo=UTC)),
            (time(8, 0), datetime(2026, 11, 16, 5, 0, tzinfo=UTC)),
        ],
        ids=["днём", "ночью", "в-начале-дня"],
    )
    def test_moment_in_day(self, at: time, expected: datetime) -> None:
        moment = moment_in_day(_TODAY, at, _DAY_START)

        assert moment == expected
        assert day_of(moment, _DAY_START) == _TODAY
        assert local_time(moment) == at


class TestDayWindow:
    def test_history_days(self) -> None:
        days = DayWindow(today=_TODAY).history_days()

        assert days[:3] == [date(2026, 11, 17), _TODAY, date(2026, 11, 15)]
        assert days[-1] == date(2026, 11, 9)
        assert len(days) == 9

    @pytest.mark.parametrize(
        ("day", "contained"),
        [
            (date(2026, 11, 17), True),
            (date(2026, 11, 9), True),
            (date(2026, 11, 8), False),
            (date(2026, 11, 18), False),
        ],
    )
    def test_contains(self, day: date, contained: bool) -> None:
        assert DayWindow(today=_TODAY).contains(day) is contained

    @pytest.mark.parametrize(
        ("day", "markable"),
        [
            (_TODAY, True),
            (date(2026, 11, 17), True),
            (date(2026, 11, 15), False),
            (date(2026, 11, 18), False),
        ],
        ids=["сегодня", "завтра", "вчера", "послезавтра"],
    )
    def test_markable(self, day: date, markable: bool) -> None:
        window = DayWindow(today=_TODAY)

        assert window.markable(day) is markable
        if markable:
            ensure_markable(window, day)
        else:
            with pytest.raises(ValidationError):
                ensure_markable(window, day)

    def test_at_uses_day_start(self) -> None:
        window = DayWindow.at(datetime(2026, 11, 16, 4, 0, tzinfo=UTC), _DAY_START)

        assert (window.yesterday, window.today, window.tomorrow) == (
            date(2026, 11, 14),
            date(2026, 11, 15),
            _TODAY,
        )
