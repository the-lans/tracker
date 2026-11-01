"""
Расход окон лимита подписки LLM-аккаунта (раздел 19.7 ТЗ).

Расход провайдер отдаёт запросом от имени учётки; прокси выполняет его сам
(`requests/api-call`) и подставляет токен, поэтому токены трекеру не
выдаются. Адреса и поля ответов провайдеры публично не документируют
(проверены в `docs/remote_control_findings.md`): ответ другого формата не
роняет вызывающий код — опрос пишет ошибку в `app_logs`, а расход остаётся
неизвестным.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from app_logging.app_logs import write_app_log
from app_logging.config import get_logger
from clients.cliproxy import CliproxyManagementClient
from db.models.enums import AppLogLevel, LlmAccountStatus
from db.models.llm import LlmAccount
from services.errors import ExternalServiceError
from services.llm_providers import UsageSource, get_provider

logger = get_logger("llm_usage")

_SOURCE = "llm_usage"
_TOKEN_HEADER = {"Authorization": "Bearer $TOKEN$"}
_HTTP_OK = 200
# Расход, при котором окно исчерпано (раздел 3.1, статус `rate_limited`).
EXHAUSTED_PCT = Decimal(100)
# Лимит исчерпан, а время сброса неизвестно: аккаунт возвращается в работу
# проверкой `check_llm_account_limits` через час (раздел 16.2).
UNKNOWN_RATE_LIMIT_WINDOW = timedelta(hours=1)
_PCT_QUANTUM = Decimal("0.01")
_FIVE_HOURS_SECONDS = 5 * 60 * 60
_WEEK_SECONDS = 7 * 24 * 60 * 60


class UsageFormatError(ValueError):
    """Ответ провайдера не того формата, что проверен (раздел 19.7)."""


@dataclass(frozen=True, slots=True)
class UsageWindow:
    pct: Decimal | None
    resets_at: datetime | None


@dataclass(frozen=True, slots=True)
class UsageSnapshot:
    five_hour: UsageWindow
    week: UsageWindow


@dataclass(frozen=True, slots=True)
class _Probe:
    url: str
    headers: Mapping[str, str]
    parse: Callable[[Mapping[str, Any]], UsageSnapshot]


def _pct(value: object) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        raise UsageFormatError(f"Расход не число: {value!r}")
    try:
        pct = Decimal(str(value)).quantize(_PCT_QUANTUM)
    except InvalidOperation as exc:
        raise UsageFormatError(f"Расход не число: {value!r}") from exc
    return min(max(pct, Decimal(0)), EXHAUSTED_PCT)


def _iso_time(value: object) -> datetime | None:
    if value is None:
        return None
    try:
        moment = datetime.fromisoformat(str(value))
    except ValueError as exc:
        raise UsageFormatError(f"Время сброса не ISO 8601: {value!r}") from exc
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def _unix_time(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise UsageFormatError(f"Время сброса не unix-время: {value!r}")
    return datetime.fromtimestamp(value, tz=UTC)


def _section(body: Mapping[str, Any], key: str) -> Mapping[str, Any] | None:
    value = body.get(key)
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise UsageFormatError(f"Поле {key} не объект")
    return value


_UNKNOWN = UsageWindow(pct=None, resets_at=None)


def _anthropic_window(body: Mapping[str, Any], key: str) -> UsageWindow:
    section = _section(body, key)
    if section is None:
        return _UNKNOWN
    return UsageWindow(
        pct=_pct(section.get("utilization")),
        resets_at=_iso_time(section.get("resets_at")),
    )


def _parse_anthropic(body: Mapping[str, Any]) -> UsageSnapshot:
    if "five_hour" not in body or "seven_day" not in body:
        raise UsageFormatError("Нет окон five_hour/seven_day")
    return UsageSnapshot(
        five_hour=_anthropic_window(body, "five_hour"),
        week=_anthropic_window(body, "seven_day"),
    )


def _openai_window(section: Mapping[str, Any] | None) -> UsageWindow:
    if section is None:
        return _UNKNOWN
    return UsageWindow(
        pct=_pct(section.get("used_percent")),
        resets_at=_unix_time(section.get("reset_at")),
    )


def _parse_openai(body: Mapping[str, Any]) -> UsageSnapshot:
    """Основное окно — 5 часов, дополнительное — неделя, если длины окон не говорят обратного."""
    rate_limit = _section(body, "rate_limit")
    if rate_limit is None:
        raise UsageFormatError("Нет rate_limit")
    primary = _section(rate_limit, "primary_window")
    secondary = _section(rate_limit, "secondary_window")
    if primary is None and secondary is None:
        raise UsageFormatError("Нет окон primary_window/secondary_window")
    swapped = (primary or {}).get("limit_window_seconds") == _WEEK_SECONDS or (
        secondary or {}
    ).get("limit_window_seconds") == _FIVE_HOURS_SECONDS
    five_hour, week = (secondary, primary) if swapped else (primary, secondary)
    return UsageSnapshot(five_hour=_openai_window(five_hour), week=_openai_window(week))


_PROBES: Mapping[UsageSource, _Probe] = {
    UsageSource.ANTHROPIC_OAUTH: _Probe(
        url="https://api.anthropic.com/api/oauth/usage",
        headers={**_TOKEN_HEADER, "anthropic-beta": "oauth-2025-04-20"},
        parse=_parse_anthropic,
    ),
    UsageSource.OPENAI_WHAM: _Probe(
        url="https://chatgpt.com/backend-api/wham/usage",
        headers=_TOKEN_HEADER,
        parse=_parse_openai,
    ),
}


def parse_usage(source: UsageSource, raw_body: str) -> UsageSnapshot:
    try:
        body = json.loads(raw_body)
    except ValueError as exc:
        raise UsageFormatError("Ответ не JSON") from exc
    if not isinstance(body, Mapping):
        raise UsageFormatError("Ответ не объект")
    return _PROBES[source].parse(body)


async def fetch_usage(
    cliproxy: CliproxyManagementClient,
    *,
    source: UsageSource,
    auth_index: str,
) -> UsageSnapshot:
    """Расход окон учётки; ответ провайдера не 200 или не того формата — `UsageFormatError`."""
    probe = _PROBES[source]
    result = await cliproxy.api_call(
        auth_index=auth_index,
        method="GET",
        url=probe.url,
        headers=probe.headers,
    )
    if result.status_code != _HTTP_OK:
        raise UsageFormatError(f"Провайдер ответил {result.status_code}")
    return parse_usage(source, result.body)


def _exhausted_until(snapshot: UsageSnapshot) -> tuple[bool, datetime | None]:
    """Исчерпано ли окно и когда сбросится: при двух исчерпанных — позднее время."""
    exhausted = [
        window
        for window in (snapshot.five_hour, snapshot.week)
        if window.pct is not None and window.pct >= EXHAUSTED_PCT
    ]
    times = [window.resets_at for window in exhausted if window.resets_at is not None]
    return bool(exhausted), max(times, default=None)


def apply_usage(account: LlmAccount, snapshot: UsageSnapshot, *, now: datetime) -> None:
    """
    Сохраняет расход в аккаунт; исчерпанное окно у `active` аккаунта — `rate_limited`
    до сброса окна (раздел 3.1). Коммит — у вызывающего кода.
    """
    account.usage_5h_pct = snapshot.five_hour.pct
    account.usage_5h_resets_at = snapshot.five_hour.resets_at
    account.usage_week_pct = snapshot.week.pct
    account.usage_week_resets_at = snapshot.week.resets_at
    account.usage_checked_at = now
    exhausted, resets_at = _exhausted_until(snapshot)
    if exhausted and account.status is LlmAccountStatus.ACTIVE:
        account.status = LlmAccountStatus.RATE_LIMITED
        account.rate_limit_resets_at = resets_at or now + UNKNOWN_RATE_LIMIT_WINDOW


async def refresh_account_usage(
    cliproxy: CliproxyManagementClient,
    account: LlmAccount,
    *,
    auth_index: str,
    now: datetime,
) -> UsageSnapshot | None:
    """
    Опрашивает расход и сохраняет его в аккаунт (без коммита). `None` — провайдер
    расход не отдаёт или опрос не удался: ошибка записана в `app_logs`, прежние
    значения не меняются.
    """
    source = get_provider(account.provider).usage_source
    if source is None:
        return None
    try:
        snapshot = await fetch_usage(cliproxy, source=source, auth_index=auth_index)
    except (UsageFormatError, ExternalServiceError) as exc:
        logger.warning("llm_usage_probe_failed", account_id=str(account.id), error=str(exc))
        await write_app_log(
            level=AppLogLevel.ERROR,
            source=_SOURCE,
            message="Не удалось получить расход окон лимита LLM-аккаунта",
            context={
                "account_id": str(account.id),
                "provider": account.provider,
                "error": str(exc),
            },
        )
        return None
    apply_usage(account, snapshot, now=now)
    return snapshot
