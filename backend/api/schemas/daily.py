"""
«Дейли» (раздел 15.8 ТЗ): дни, отметки задач, события, планы и шаблон;
подключение к Google Calendar (раздел 19.8).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, time

from pydantic import BaseModel, ConfigDict, Field

from db.models.daily import DailyEvent
from db.models.enums import DailyEventSource, GoogleCalendarStatus, TaskStatus
from services.daily_events import MAX_EVENT_NOTES_LENGTH, MAX_EVENT_TITLE_LENGTH
from services.daily_history import DayFact
from services.daily_plans import MAX_DAILY_TEXT_LENGTH
from services.google_calendar import MAX_SYNCED_CALENDARS
from services.tracker_day import local_time


class DailyCalendarResponse(BaseModel):
    """Дни «Дейли» по началу дня из настроек: вкладка «История» и фильтр дашборда."""

    today: date
    yesterday: date
    tomorrow: date
    history_days: list[date]
    day_start_time: time


class TaskDayMarksResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    task_id: uuid.UUID
    days: list[date]


class DailyMarkedTaskResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    title: str
    status: TaskStatus
    # None — день ещё не наступил.
    fact: DayFact | None


class DailyEventResponse(BaseModel):
    id: uuid.UUID
    source: DailyEventSource
    day: date
    end_day: date
    starts_at: datetime | None
    ends_at: datetime | None
    # Время по Москве — как его вводят в форме события.
    start_time: time | None
    end_time: time | None
    title: str
    notes: str | None
    hidden: bool

    @classmethod
    def of(cls, event: DailyEvent) -> DailyEventResponse:
        return cls(
            id=event.id,
            source=event.source,
            day=event.day,
            end_day=event.end_day,
            starts_at=event.starts_at,
            ends_at=event.ends_at,
            start_time=local_time(event.starts_at) if event.starts_at else None,
            end_time=local_time(event.ends_at) if event.ends_at else None,
            title=event.title,
            notes=event.notes,
            hidden=event.hidden,
        )


class DailyDayResponse(BaseModel):
    day: date
    tasks: list[DailyMarkedTaskResponse]
    events: list[DailyEventResponse]


class DailyEventRequest(BaseModel):
    """Ручное событие: время необязательно, без него событие — на весь день."""

    day: date
    title: str = Field(min_length=1, max_length=MAX_EVENT_TITLE_LENGTH)
    notes: str | None = Field(default=None, max_length=MAX_EVENT_NOTES_LENGTH)
    start_time: time | None = None
    end_time: time | None = None


class DailyEventVisibilityRequest(BaseModel):
    hidden: bool


class DailyPlanResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    day: date
    content: str
    created_at: datetime
    updated_at: datetime


class DailyPlanCreateRequest(BaseModel):
    day: date


class DailyPlanUpdateRequest(BaseModel):
    content: str = Field(max_length=MAX_DAILY_TEXT_LENGTH)


class DailyTemplateResponse(BaseModel):
    content: str
    is_default: bool
    # Переменные шаблона `{{daily.*}}` — для подсказки в форме.
    variables: list[str]


class DailyTemplateRequest(BaseModel):
    content: str = Field(min_length=1, max_length=MAX_DAILY_TEXT_LENGTH)


class DailyTemplatePreviewResponse(BaseModel):
    content: str


class GoogleCalendarConnectionResponse(BaseModel):
    """Раздел 19.8: подключение к Google Calendar; токен наружу не отдаётся."""

    model_config = ConfigDict(from_attributes=True)

    google_email: str
    status: GoogleCalendarStatus
    calendar_ids: list[str]
    last_synced_at: datetime | None
    last_error: str | None


class GoogleCalendarInfoResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    summary: str
    primary: bool


class GoogleCalendarLoginResponse(BaseModel):
    url: str


class GoogleCalendarSelectionRequest(BaseModel):
    calendar_ids: list[str] = Field(min_length=1, max_length=MAX_SYNCED_CALENDARS)


class GoogleCalendarSyncResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    synced: bool
    events: int
