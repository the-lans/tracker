"""
Правило выбора LLM-аккаунта хода (раздел 19.7 ТЗ) — чистые функции без БД.

Задачи пользователя идут параллельно, а 5-часовые окна его аккаунтов
стартуют с равным шагом `5 ч / N`: новое окно открывается сразу, если
запущенных нет, иначе — на границе хода по плановому шагу и не больше окон,
чем задач в работе. Квоту окна, которое скоро сбросится с большим остатком,
забирают первой. Порог 5-часового окна не переступается: если запущенных и
свободных аккаунтов нет — `LimitWait` до ближайшего сброса.

Сбор данных, блокировка и побочные эффекты — в `services/account_router.py`.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING

from db.models.enums import LlmAccountStatus, LlmSwitchReason
from services.llm_providers import PROVIDERS

if TYPE_CHECKING:
    from db.models.llm import LlmAccount

# Раздел 19.7: длина короткого окна лимита у провайдеров.
FIVE_HOUR_WINDOW = timedelta(hours=5)
_WEEK = timedelta(days=7)
FULL_USAGE_PCT = Decimal(100)
# Резерв на идущий ход, пока у аккаунта нет своей истории стоимости хода.
DEFAULT_TURN_COST_PCT = Decimal(1)
# Балансировка не гоняет задачу между окнами по мелочи: переход в другое
# запущенное окно — только если оно заметно срочнее текущего.
BALANCE_SWITCH_GAIN = 1.5
# Нижняя граница времени до сброса: срочность конечна и у окна на грани сброса.
_MIN_HOURS = 1 / 60
_HOUR = timedelta(hours=1)
# Ожидание не короче минуты: сброс, который по данным уже наступил, но опрос
# расхода ещё не обновил аккаунт, не крутит задачу в цикле «продолжить — ждать».
MIN_LIMIT_WAIT = timedelta(minutes=1)

_IN_WORK_STATUSES = frozenset({LlmAccountStatus.ACTIVE, LlmAccountStatus.RATE_LIMITED})
_STATUS_REASONS = {
    LlmAccountStatus.RATE_LIMITED: LlmSwitchReason.RATE_LIMITED,
    LlmAccountStatus.LOGIN_REQUIRED: LlmSwitchReason.LOGIN_REQUIRED,
    LlmAccountStatus.DISABLED: LlmSwitchReason.DISABLED,
}


class NoLlmAccountAvailableError(Exception):
    """У автора задачи нет ни одного аккаунта, которым можно выполнить ход (п. 5)."""

    message = "Нет доступного LLM-аккаунта"

    def __init__(self) -> None:
        super().__init__(self.message)


class LlmLimitWaitError(Exception):
    """
    Все аккаунты автора на пороге или исчерпаны (п. 5): ход ждёт сброса до
    ``until``. Обычно это ловят ворота лимита до хода; здесь — гонка после них.
    ``attempt`` — попытка ноды пайплайна, которая ждёт: после сброса счёт
    повторов продолжается с неё, а не начинается заново.
    """

    message = "Все LLM-аккаунты на пороге — ход ждёт сброса лимита"

    def __init__(self, until: datetime, *, attempt: int = 1) -> None:
        super().__init__(self.message)
        self.until = until
        self.attempt = attempt


class LimitState(StrEnum):
    """Состояние аккаунта для выбора и для бейджа в списке аккаунтов."""

    EXCLUDED = "excluded"
    EXHAUSTED = "exhausted"
    AT_THRESHOLD = "at_threshold"
    RUNNING = "running"
    FREE = "free"


@dataclass(frozen=True, slots=True)
class AccountView:
    """
    Аккаунт автора и его нагрузка: задачи, работающие на нём, и ходы, идущие
    на нём прямо сейчас (без хода выбирающей задачи).
    """

    account: LlmAccount
    tasks: int = 0
    running_turns: int = 0


@dataclass(frozen=True, slots=True)
class AccountLimit:
    state: LimitState
    # Когда состояние кончится: сброс окна или недели; None — не ограничено.
    until: datetime | None = None


@dataclass(frozen=True, slots=True)
class ChoiceRequest:
    """
    Чем задаётся выбор хода: ``boundary`` — ход начинает ноду, её повтор,
    ручной запрос или разрешение конфликта ребейза; ``tasks_in_work`` —
    задачи автора, которым сейчас нужен аккаунт.
    """

    now: datetime
    threshold_pct: int
    current_id: uuid.UUID | None
    start_id: uuid.UUID | None
    plan_prompt: bool = False
    boundary: bool = True
    tasks_in_work: int = 1


@dataclass(frozen=True, slots=True)
class AccountChoice:
    account: LlmAccount
    reason: LlmSwitchReason
    # Аккаунт свободен: ход открывает его 5-часовое окно.
    opens_window: bool = False


@dataclass(frozen=True, slots=True)
class LimitWait:
    """Все аккаунты на пороге или исчерпаны — ход ждёт ближайшего сброса."""

    until: datetime


def _suitable(account: LlmAccount, *, plan_prompt: bool) -> bool:
    provider = PROVIDERS.get(account.provider)
    if provider is None or account.default_model is None:
        return False
    return provider.plan_prompt_allowed or not plan_prompt


def window_end(account: LlmAccount, *, now: datetime) -> datetime | None:
    """Когда сбросится идущее 5-часовое окно; None — окно не идёт."""
    resets_at = account.usage_5h_resets_at
    if resets_at is not None and resets_at > now:
        return resets_at
    started_at = account.window_started_at
    if started_at is not None and started_at + FIVE_HOUR_WINDOW > now:
        return started_at + FIVE_HOUR_WINDOW
    return None


def _window_start(account: LlmAccount, *, now: datetime) -> datetime | None:
    end = window_end(account, now=now)
    return end - FIVE_HOUR_WINDOW if end is not None else None


def _usage_5h(account: LlmAccount, *, now: datetime) -> Decimal | None:
    """Расход идущего 5-часового окна; после его сброса прежний расход не действует."""
    resets_at = account.usage_5h_resets_at
    if resets_at is not None and resets_at <= now:
        return None
    return account.usage_5h_pct


def _reserve_pct(view: AccountView) -> Decimal:
    cost = view.account.turn_cost_pct
    return (cost if cost is not None else DEFAULT_TURN_COST_PCT) * view.running_turns


def _not_reset(resets_at: datetime | None, *, now: datetime) -> bool:
    return resets_at is None or resets_at > now


def _exhausted(account: LlmAccount, *, now: datetime) -> AccountLimit | None:
    """
    Лимит провайдера (`rate_limited`) или неделя исчерпаны; None — нет или
    сброс уже наступил, а опрос ещё не обновил аккаунт.
    """
    resets_at = account.rate_limit_resets_at
    if account.status is LlmAccountStatus.RATE_LIMITED and _not_reset(resets_at, now=now):
        return AccountLimit(LimitState.EXHAUSTED, until=resets_at)
    week = account.usage_week_pct
    resets_at = account.usage_week_resets_at
    if week is not None and week >= FULL_USAGE_PCT and _not_reset(resets_at, now=now):
        return AccountLimit(LimitState.EXHAUSTED, until=resets_at)
    return None


def limit_state(
    view: AccountView,
    *,
    threshold_pct: int,
    now: datetime,
    plan_prompt: bool = False,
) -> AccountLimit:
    """Состояние аккаунта по таблице раздела 19.7."""
    account = view.account
    if account.status not in _IN_WORK_STATUSES or not _suitable(account, plan_prompt=plan_prompt):
        return AccountLimit(LimitState.EXCLUDED)
    exhausted = _exhausted(account, now=now)
    if exhausted is not None:
        return exhausted
    end = window_end(account, now=now)
    usage = _usage_5h(account, now=now)
    if usage is not None and usage + _reserve_pct(view) >= threshold_pct:
        return AccountLimit(LimitState.AT_THRESHOLD, until=end or now + FIVE_HOUR_WINDOW)
    if end is not None:
        return AccountLimit(LimitState.RUNNING, until=end)
    return AccountLimit(LimitState.FREE)


def _hours_until(moment: datetime | None, *, now: datetime, default: timedelta) -> float:
    span = moment - now if moment is not None and moment > now else default
    return max(span / _HOUR, _MIN_HOURS)


def _urgency(account: LlmAccount, *, threshold_pct: int, now: datetime) -> float:
    """Темп, с которым окно нужно расходовать, чтобы квота не сгорела."""
    usage = _usage_5h(account, now=now)
    if usage is None:
        return 0.0
    hours = _hours_until(window_end(account, now=now), now=now, default=FIVE_HOUR_WINDOW)
    return float(Decimal(threshold_pct) - usage) / hours


def _free_order(account: LlmAccount, *, now: datetime) -> tuple[int, float, int]:
    """
    Какое свободное окно открыть первым: неделя, которая сгорит раньше
    одного окна, затем — наибольшее недельное давление.
    """
    week = account.usage_week_pct
    if week is None:
        return (2, 0.0, account.switch_order)
    hours = _hours_until(account.usage_week_resets_at, now=now, default=_WEEK)
    expiring = hours < FIVE_HOUR_WINDOW / _HOUR
    pressure = float(FULL_USAGE_PCT - week) / hours
    return (0 if expiring else 1, -pressure, account.switch_order)


def _leave_reason(limit: AccountLimit, account: LlmAccount) -> LlmSwitchReason:
    """Почему прежний аккаунт задачи этот ход не выполняет."""
    status_reason = _STATUS_REASONS.get(account.status)
    if status_reason is not None:
        return status_reason
    if limit.state is LimitState.EXHAUSTED:
        return LlmSwitchReason.WEEK_EXHAUSTED
    if limit.state is LimitState.AT_THRESHOLD:
        return LlmSwitchReason.THRESHOLD_5H
    return LlmSwitchReason.UNSUITABLE


@dataclass(frozen=True, slots=True)
class _Pool:
    request: ChoiceRequest
    views: dict[uuid.UUID, AccountView]
    limits: dict[uuid.UUID, AccountLimit]

    def ids(self, state: LimitState) -> list[uuid.UUID]:
        return [key for key, limit in self.limits.items() if limit.state is state]

    def account(self, account_id: uuid.UUID) -> LlmAccount:
        return self.views[account_id].account

    def score(self, account_id: uuid.UUID) -> float:
        """Срочность на задачу: у текущего окна задача уже учтена в нагрузке."""
        request = self.request
        view = self.views[account_id]
        urgency = _urgency(view.account, threshold_pct=request.threshold_pct, now=request.now)
        if account_id == request.current_id:
            return urgency / max(view.tasks, 1)
        return urgency / (view.tasks + 1)

    def planned_step_passed(self) -> bool:
        request = self.request
        starts = [
            start
            for view in self.views.values()
            if (start := _window_start(view.account, now=request.now)) is not None
        ]
        available = len(self.ids(LimitState.RUNNING)) + len(self.ids(LimitState.FREE))
        if not starts or available == 0:
            return True
        return request.now - max(starts) >= FIVE_HOUR_WINDOW / available


def _pool(views: Sequence[AccountView], request: ChoiceRequest) -> _Pool:
    return _Pool(
        request=request,
        views={view.account.id: view for view in views},
        limits={
            view.account.id: limit_state(
                view,
                threshold_pct=request.threshold_pct,
                now=request.now,
                plan_prompt=request.plan_prompt,
            )
            for view in views
        },
    )


def _wait_or_fail(pool: _Pool) -> LimitWait:
    blocked = pool.ids(LimitState.AT_THRESHOLD) + pool.ids(LimitState.EXHAUSTED)
    if not blocked:
        raise NoLlmAccountAvailableError
    now = pool.request.now
    moments = [until for key in blocked if (until := pool.limits[key].until) is not None]
    until = min(moments) if moments else now + FIVE_HOUR_WINDOW
    return LimitWait(until=max(until, now + MIN_LIMIT_WAIT))


def _switch_reason(pool: _Pool, *, chosen_running: bool) -> LlmSwitchReason:
    request = pool.request
    previous_id = request.current_id or request.start_id
    if previous_id is None or previous_id not in pool.views:
        return LlmSwitchReason.START
    limit = pool.limits[previous_id]
    if limit.state in {LimitState.RUNNING, LimitState.FREE}:
        if request.current_id is None:
            return LlmSwitchReason.START
        return LlmSwitchReason.WINDOW_BALANCE if chosen_running else LlmSwitchReason.WINDOW_PLANNED
    return _leave_reason(limit, pool.account(previous_id))


def _choice(pool: _Pool, account_id: uuid.UUID) -> AccountChoice:
    request = pool.request
    opens = pool.limits[account_id].state is LimitState.FREE
    if account_id == request.current_id:
        reason = LlmSwitchReason.KEPT
    elif request.current_id is None and account_id == request.start_id:
        reason = LlmSwitchReason.START
    else:
        reason = _switch_reason(pool, chosen_running=not opens)
    return AccountChoice(pool.account(account_id), reason, opens_window=opens)


def _should_open_window(pool: _Pool, running: list[uuid.UUID]) -> bool:
    request = pool.request
    if not running:
        return True
    return request.boundary and len(running) < request.tasks_in_work and pool.planned_step_passed()


def _best_running(pool: _Pool, running: list[uuid.UUID]) -> uuid.UUID:
    request = pool.request
    best = max(running, key=lambda key: (pool.score(key), -pool.account(key).switch_order))
    current = request.current_id
    if current in running and pool.score(best) <= pool.score(current) * BALANCE_SWITCH_GAIN:
        return current
    return best


def choose_account(
    views: Sequence[AccountView],
    request: ChoiceRequest,
) -> AccountChoice | LimitWait:
    """
    Аккаунт хода по пп. 1–5 раздела 19.7. `views` — все аккаунты автора
    задачи; `NoLlmAccountAvailableError` — все аккаунты исключены.
    """
    pool = _pool(views, request)
    running = pool.ids(LimitState.RUNNING)
    free = pool.ids(LimitState.FREE)
    if not running and not free:
        return _wait_or_fail(pool)
    current = request.current_id
    if current in running and not request.boundary:
        return _choice(pool, current)
    start = request.start_id
    if current is None and start is not None and (start in running or start in free):
        return _choice(pool, start)
    if free and _should_open_window(pool, running):
        # Окно сбросилось у текущего аккаунта — он и открывает новое: кеш промта тот же.
        if current in free:
            return _choice(pool, current)
        opened = min(free, key=lambda key: _free_order(pool.account(key), now=request.now))
        return _choice(pool, opened)
    return _choice(pool, _best_running(pool, running))


def wait_until(
    views: Sequence[AccountView],
    request: ChoiceRequest,
) -> datetime | None:
    """Ворота лимита: время ожидания, если ход сейчас начинать нельзя."""
    try:
        choice = choose_account(views, request)
    except NoLlmAccountAvailableError:
        return None
    return choice.until if isinstance(choice, LimitWait) else None
