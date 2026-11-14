"""
Планы на день и шаблон плана «Дейли» (раздел 15.8 ТЗ).

План собирается по шаблону пользователя один раз — при создании или по
кнопке «Пересобрать» — и дальше правится вручную. Шаблон — текст с
переменными `{{daily.*}}` (синтаксис раздела 5, без циклов): списки задач и
событий подставляются готовыми строками. Пока пользователь не сохранил свой
шаблон, действует `DEFAULT_DAILY_TEMPLATE`.

«Сделано» — задачи, отмеченные на прошлый день, по которым в нём была
работа; прошлый день — последний день до дня плана с отметками или
событиями.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING

from app_logging.config import get_logger
from db.models.daily import DailyPlan, DailyPlanTemplate
from db.models.enums import DailyEventSource
from db.queries.daily import select_plan, select_plans
from services.access import get_personal_or_404
from services.daily_history import MarkedTask, day_view, previous_day
from services.errors import ConflictError, ValidationError
from services.integrity import commit_or_conflict
from services.templating import VARIABLE_PATTERN, render_template
from services.tracker_day import ensure_in_history

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.ext.asyncio import AsyncSession

    from db.models.daily import DailyEvent
    from db.models.users import User
    from services.daily_clock import DailyClock

logger = get_logger("daily_plans")

DAILY_NAMESPACE = "daily"
DAILY_FIELDS = frozenset(
    {
        "date",
        "previous_date",
        "yesterday",
        "today",
        "done",
        "planned",
        "events",
        "previous_events",
    },
)
MAX_DAILY_TEXT_LENGTH = 20_000
PLANS_PAGE_SIZE = 30
DATE_FORMAT = "%d.%m.%Y"
EMPTY_LIST = "—"
BULLET = "• "
# Событие из календаря — встреча; ручное событие выводится как записано.
MEETING_PREFIX = "Встреча: "
_SENTENCE_END = ".!?…"

DEFAULT_DAILY_TEMPLATE = """Доброго всем утра!

Вчера:
{{daily.yesterday}}

Сегодня:
{{daily.today}}
"""

_NOT_FOUND = "План на день не найден"
_PLAN_EXISTS = "План на этот день уже есть — откройте его или пересоберите по шаблону"
_TEXT_TOO_LONG = f"Текст — не длиннее {MAX_DAILY_TEXT_LENGTH} символов"
_EMPTY_TEMPLATE = "Шаблон не может быть пустым"


@dataclass(frozen=True, slots=True)
class DailyTemplate:
    content: str
    is_default: bool


def validate_daily_text(text: str) -> None:
    if len(text) > MAX_DAILY_TEXT_LENGTH:
        raise ValidationError(_TEXT_TOO_LONG)


def validate_daily_template(content: str) -> None:
    """Раздел 5.1: неизвестная переменная — ошибка сохранения, а не рендера."""
    if not content.strip():
        raise ValidationError(_EMPTY_TEMPLATE)
    validate_daily_text(content)
    unknown = sorted(
        {
            f"{namespace}.{field}"
            for namespace, field in VARIABLE_PATTERN.findall(content)
            if namespace != DAILY_NAMESPACE or field not in DAILY_FIELDS
        },
    )
    if unknown:
        listed = ", ".join(f"{{{{{name}}}}}" for name in unknown)
        raise ValidationError(f"Неизвестные переменные шаблона: {listed}")


def _sentence(text: str) -> str:
    text = text.strip()
    return text if text.endswith(tuple(_SENTENCE_END)) else f"{text}."


def _task_line(task: MarkedTask) -> str:
    return _sentence(f"{task.code}: {task.title}")


def _event_line(event: DailyEvent) -> str:
    prefix = MEETING_PREFIX if event.source is DailyEventSource.GOOGLE else ""
    return _sentence(f"{prefix}{event.title}")


def _bullets(lines: Sequence[str]) -> str:
    return "\n".join(f"{BULLET}{line}" for line in lines) or EMPTY_LIST


def _format_day(day: date | None) -> str:
    return day.strftime(DATE_FORMAT) if day is not None else EMPTY_LIST


async def _render(
    db_session: AsyncSession,
    *,
    user: User,
    day: date,
    clock: DailyClock,
    template: str,
) -> str:
    view = await day_view(db_session, user=user, day=day, clock=clock, include_hidden=False)
    previous = await previous_day(db_session, user=user, before=day, clock=clock)
    context = {
        "daily.date": _format_day(day),
        "daily.previous_date": _format_day(previous.day),
        "daily.done": _bullets([_task_line(task) for task in previous.done]),
        "daily.planned": _bullets([_task_line(task) for task in view.tasks]),
        "daily.events": _bullets([_event_line(event) for event in view.events]),
        "daily.previous_events": _bullets([_event_line(event) for event in previous.events]),
        # Раздел 15.8: «Вчера» — сделанные задачи и события прошлого дня,
        # «Сегодня» — события дня, затем отмеченные задачи.
        "daily.yesterday": _bullets(
            [_task_line(task) for task in previous.done]
            + [_event_line(event) for event in previous.events],
        ),
        "daily.today": _bullets(
            [_event_line(event) for event in view.events]
            + [_task_line(task) for task in view.tasks],
        ),
    }
    return render_template(template, context)


async def get_daily_template(db_session: AsyncSession, *, user: User) -> DailyTemplate:
    stored = await db_session.get(DailyPlanTemplate, user.id)
    if stored is None:
        return DailyTemplate(content=DEFAULT_DAILY_TEMPLATE, is_default=True)
    return DailyTemplate(content=stored.content, is_default=False)


async def save_daily_template(
    db_session: AsyncSession,
    *,
    user: User,
    content: str,
) -> DailyTemplate:
    validate_daily_template(content)
    stored = await db_session.get(DailyPlanTemplate, user.id)
    if stored is None:
        db_session.add(DailyPlanTemplate(user_id=user.id, content=content))
    else:
        stored.content = content
    await db_session.commit()
    logger.info("daily_template_saved")
    return DailyTemplate(content=content, is_default=False)


async def reset_daily_template(db_session: AsyncSession, *, user: User) -> DailyTemplate:
    stored = await db_session.get(DailyPlanTemplate, user.id)
    if stored is not None:
        await db_session.delete(stored)
        await db_session.commit()
    logger.info("daily_template_reset")
    return DailyTemplate(content=DEFAULT_DAILY_TEMPLATE, is_default=True)


async def preview_daily_template(
    db_session: AsyncSession,
    *,
    user: User,
    content: str,
    clock: DailyClock,
) -> str:
    """Шаблон, собранный на сегодня, — без сохранения шаблона и плана."""
    validate_daily_template(content)
    return await _render(
        db_session,
        user=user,
        day=clock.window.today,
        clock=clock,
        template=content,
    )


async def _render_with_user_template(
    db_session: AsyncSession,
    *,
    user: User,
    day: date,
    clock: DailyClock,
) -> str:
    template = await get_daily_template(db_session, user=user)
    return await _render(db_session, user=user, day=day, clock=clock, template=template.content)


async def get_plan_for_user(
    db_session: AsyncSession,
    plan_id: uuid.UUID,
    *,
    user: User,
) -> DailyPlan:
    return await get_personal_or_404(
        db_session,
        DailyPlan,
        plan_id,
        user=user,
        not_found=_NOT_FOUND,
    )


async def list_daily_plans(db_session: AsyncSession, *, user: User) -> list[DailyPlan]:
    return await select_plans(db_session, user_id=user.id, limit=PLANS_PAGE_SIZE)


async def create_daily_plan(
    db_session: AsyncSession,
    *,
    user: User,
    day: date,
    clock: DailyClock,
) -> DailyPlan:
    ensure_in_history(clock.window, day)
    if await select_plan(db_session, user_id=user.id, day=day) is not None:
        raise ConflictError(_PLAN_EXISTS)
    content = await _render_with_user_template(db_session, user=user, day=day, clock=clock)
    plan = DailyPlan(user_id=user.id, day=day, content=content)
    db_session.add(plan)
    # Два одновременных создания одного дня: второе упирается в UNIQUE.
    await commit_or_conflict(db_session, message=_PLAN_EXISTS)
    logger.info("daily_plan_created", plan_id=str(plan.id), day=day.isoformat())
    return plan


async def update_daily_plan(
    db_session: AsyncSession,
    *,
    user: User,
    plan_id: uuid.UUID,
    content: str,
) -> DailyPlan:
    validate_daily_text(content)
    plan = await get_plan_for_user(db_session, plan_id, user=user)
    plan.content = content
    await db_session.commit()
    # `updated_at` выставляет БД (onupdate) — перечитать для ответа.
    await db_session.refresh(plan)
    logger.info("daily_plan_updated", plan_id=str(plan.id))
    return plan


async def regenerate_daily_plan(
    db_session: AsyncSession,
    *,
    user: User,
    plan_id: uuid.UUID,
    clock: DailyClock,
) -> DailyPlan:
    """Текст плана заменяется сборкой по текущему шаблону — ручные правки теряются."""
    plan = await get_plan_for_user(db_session, plan_id, user=user)
    plan.content = await _render_with_user_template(
        db_session,
        user=user,
        day=plan.day,
        clock=clock,
    )
    await db_session.commit()
    await db_session.refresh(plan)
    logger.info("daily_plan_regenerated", plan_id=str(plan.id))
    return plan


async def delete_daily_plan(
    db_session: AsyncSession,
    *,
    user: User,
    plan_id: uuid.UUID,
) -> None:
    plan = await get_plan_for_user(db_session, plan_id, user=user)
    await db_session.delete(plan)
    await db_session.commit()
    logger.info("daily_plan_deleted", plan_id=str(plan_id))
