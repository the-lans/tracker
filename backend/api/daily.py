"""
«Дейли» (раздел 15.8 ТЗ): дни, история дня, отметки задач, события, планы на
день и шаблон плана. Всё личное — только записи текущего пользователя, в том
числе у администратора.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_current_user
from api.schemas import (
    DailyCalendarResponse,
    DailyDayResponse,
    DailyEventRequest,
    DailyEventResponse,
    DailyEventVisibilityRequest,
    DailyMarkedTaskResponse,
    DailyPlanCreateRequest,
    DailyPlanResponse,
    DailyPlanUpdateRequest,
    DailyTemplatePreviewResponse,
    DailyTemplateRequest,
    DailyTemplateResponse,
    TaskDayMarksResponse,
)
from db.models.daily import DailyPlan
from db.models.users import User
from db.session import get_session
from services.daily_clock import load_daily_clock
from services.daily_events import (
    ManualEventValues,
    create_manual_event,
    delete_manual_event,
    set_event_hidden,
    update_manual_event,
)
from services.daily_history import history_day_view
from services.daily_plans import (
    DAILY_FIELDS,
    DAILY_NAMESPACE,
    DailyTemplate,
    create_daily_plan,
    delete_daily_plan,
    get_daily_template,
    get_plan_for_user,
    list_daily_plans,
    preview_daily_template,
    regenerate_daily_plan,
    reset_daily_template,
    save_daily_template,
    update_daily_plan,
)
from services.day_marks import TaskDayMarks, recent_day_marks

router = APIRouter(prefix="/daily", tags=["daily"])

CurrentUser = Annotated[User, Depends(get_current_user)]
DbSession = Annotated[AsyncSession, Depends(get_session)]

_TEMPLATE_VARIABLES = sorted(f"{DAILY_NAMESPACE}.{field}" for field in DAILY_FIELDS)


def _now() -> datetime:
    return datetime.now(UTC)


def _event_values(body: DailyEventRequest) -> ManualEventValues:
    return ManualEventValues(
        day=body.day,
        title=body.title,
        notes=body.notes,
        start_time=body.start_time,
        end_time=body.end_time,
    )


def _template_response(template: DailyTemplate) -> DailyTemplateResponse:
    return DailyTemplateResponse(
        content=template.content,
        is_default=template.is_default,
        variables=_TEMPLATE_VARIABLES,
    )


@router.get("/calendar", response_model=DailyCalendarResponse)
async def read_calendar(db_session: DbSession, _current_user: CurrentUser) -> DailyCalendarResponse:
    clock = await load_daily_clock(db_session, now=_now())
    window = clock.window
    return DailyCalendarResponse(
        today=window.today,
        yesterday=window.yesterday,
        tomorrow=window.tomorrow,
        history_days=window.history_days(),
        day_start_time=clock.day_start,
    )


@router.get("/marks", response_model=list[TaskDayMarksResponse])
async def read_recent_marks(db_session: DbSession, current_user: CurrentUser) -> list[TaskDayMarks]:
    """Раздел 15.1: отметки вчера, сегодня и завтра — для фильтра дашборда."""
    return await recent_day_marks(db_session, user=current_user, now=_now())


@router.get("/days/{day}", response_model=DailyDayResponse)
async def read_day(day: date, db_session: DbSession, current_user: CurrentUser) -> DailyDayResponse:
    clock = await load_daily_clock(db_session, now=_now())
    view = await history_day_view(db_session, user=current_user, day=day, clock=clock)
    return DailyDayResponse(
        day=view.day,
        tasks=[DailyMarkedTaskResponse.model_validate(task) for task in view.tasks],
        events=[DailyEventResponse.of(event) for event in view.events],
    )


@router.post("/events", response_model=DailyEventResponse, status_code=201)
async def create_event(
    body: DailyEventRequest,
    db_session: DbSession,
    current_user: CurrentUser,
) -> DailyEventResponse:
    clock = await load_daily_clock(db_session, now=_now())
    event = await create_manual_event(
        db_session,
        user=current_user,
        values=_event_values(body),
        clock=clock,
    )
    return DailyEventResponse.of(event)


@router.put("/events/{event_id}", response_model=DailyEventResponse)
async def update_event(
    event_id: uuid.UUID,
    body: DailyEventRequest,
    db_session: DbSession,
    current_user: CurrentUser,
) -> DailyEventResponse:
    clock = await load_daily_clock(db_session, now=_now())
    event = await update_manual_event(
        db_session,
        user=current_user,
        event_id=event_id,
        values=_event_values(body),
        clock=clock,
    )
    return DailyEventResponse.of(event)


@router.put("/events/{event_id}/hidden", response_model=DailyEventResponse)
async def update_event_visibility(
    event_id: uuid.UUID,
    body: DailyEventVisibilityRequest,
    db_session: DbSession,
    current_user: CurrentUser,
) -> DailyEventResponse:
    event = await set_event_hidden(
        db_session,
        user=current_user,
        event_id=event_id,
        hidden=body.hidden,
    )
    return DailyEventResponse.of(event)


@router.delete("/events/{event_id}", status_code=204)
async def delete_event(
    event_id: uuid.UUID,
    db_session: DbSession,
    current_user: CurrentUser,
) -> None:
    await delete_manual_event(db_session, user=current_user, event_id=event_id)


@router.get("/plans", response_model=list[DailyPlanResponse])
async def read_plans(db_session: DbSession, current_user: CurrentUser) -> list[DailyPlan]:
    return await list_daily_plans(db_session, user=current_user)


@router.post("/plans", response_model=DailyPlanResponse, status_code=201)
async def create_plan(
    body: DailyPlanCreateRequest,
    db_session: DbSession,
    current_user: CurrentUser,
) -> DailyPlan:
    clock = await load_daily_clock(db_session, now=_now())
    return await create_daily_plan(db_session, user=current_user, day=body.day, clock=clock)


@router.get("/plans/{plan_id}", response_model=DailyPlanResponse)
async def read_plan(
    plan_id: uuid.UUID,
    db_session: DbSession,
    current_user: CurrentUser,
) -> DailyPlan:
    return await get_plan_for_user(db_session, plan_id, user=current_user)


@router.put("/plans/{plan_id}", response_model=DailyPlanResponse)
async def update_plan(
    plan_id: uuid.UUID,
    body: DailyPlanUpdateRequest,
    db_session: DbSession,
    current_user: CurrentUser,
) -> DailyPlan:
    return await update_daily_plan(
        db_session,
        user=current_user,
        plan_id=plan_id,
        content=body.content,
    )


@router.post("/plans/{plan_id}/regenerate", response_model=DailyPlanResponse)
async def regenerate_plan(
    plan_id: uuid.UUID,
    db_session: DbSession,
    current_user: CurrentUser,
) -> DailyPlan:
    clock = await load_daily_clock(db_session, now=_now())
    return await regenerate_daily_plan(
        db_session,
        user=current_user,
        plan_id=plan_id,
        clock=clock,
    )


@router.delete("/plans/{plan_id}", status_code=204)
async def delete_plan(plan_id: uuid.UUID, db_session: DbSession, current_user: CurrentUser) -> None:
    await delete_daily_plan(db_session, user=current_user, plan_id=plan_id)


@router.get("/template", response_model=DailyTemplateResponse)
async def read_template(db_session: DbSession, current_user: CurrentUser) -> DailyTemplateResponse:
    return _template_response(await get_daily_template(db_session, user=current_user))


@router.put("/template", response_model=DailyTemplateResponse)
async def update_template(
    body: DailyTemplateRequest,
    db_session: DbSession,
    current_user: CurrentUser,
) -> DailyTemplateResponse:
    template = await save_daily_template(db_session, user=current_user, content=body.content)
    return _template_response(template)


@router.delete("/template", response_model=DailyTemplateResponse)
async def reset_template(db_session: DbSession, current_user: CurrentUser) -> DailyTemplateResponse:
    """Возврат к шаблону по умолчанию."""
    return _template_response(await reset_daily_template(db_session, user=current_user))


@router.post("/template/preview", response_model=DailyTemplatePreviewResponse)
async def preview_template(
    body: DailyTemplateRequest,
    db_session: DbSession,
    current_user: CurrentUser,
) -> DailyTemplatePreviewResponse:
    clock = await load_daily_clock(db_session, now=_now())
    content = await preview_daily_template(
        db_session,
        user=current_user,
        content=body.content,
        clock=clock,
    )
    return DailyTemplatePreviewResponse(content=content)
