"""
Реестр провайдеров LLM-аккаунтов (раздел 19.7 ТЗ).

Провайдер — подписка, вход в которую выполняет CLIProxyAPI. Запись реестра
задаёт имя провайдера во входе OAuth прокси, перевод общей шкалы уровня
рассуждений на шкалу провайдера, способ опроса расхода окон лимита и
допустимость для нод `plan_prompt`. Новый провайдер прокси добавляется одной
записью без изменения схемы БД.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

from db.models.enums import ReasoningEffort
from services.errors import ValidationError

_E = ReasoningEffort


class UsageSource(StrEnum):
    """Откуда берётся расход окон лимита подписки (`services/llm_usage.py`)."""

    ANTHROPIC_OAUTH = "anthropic_oauth"
    OPENAI_WHAM = "openai_wham"


@dataclass(frozen=True)
class LlmProvider:
    id: str
    label: str
    # Значение `provider` в `GET /v8/management/oauth/auth-url` прокси.
    oauth_provider: str
    # Уровень трекера → уровень, который получает провайдер.
    effort_levels: Mapping[ReasoningEffort, ReasoningEffort]
    # None — провайдер расход окон не отдаёт: аккаунт переключается только по лимиту.
    usage_source: UsageSource | None
    # Проверено ли, что `plan`-режим, `ExitPlanMode` и вопросы агента работают
    # на моделях провайдера (раздел 19.7, `docs/remote_control_findings.md`).
    plan_prompt_allowed: bool


def _nearest_lower(*supported: ReasoningEffort) -> Mapping[ReasoningEffort, ReasoningEffort]:
    """Неподдерживаемый уровень — ближайший меньший из поддерживаемых (раздел 19.7)."""
    scale = list(ReasoningEffort)
    levels: dict[ReasoningEffort, ReasoningEffort] = {}
    current = supported[0]
    for effort in scale:
        if effort in supported:
            current = effort
        levels[effort] = current
    return MappingProxyType(levels)


PROVIDERS: Mapping[str, LlmProvider] = MappingProxyType(
    {
        provider.id: provider
        for provider in (
            LlmProvider(
                id="anthropic",
                label="Claude (Anthropic)",
                oauth_provider="claude",
                effort_levels=_nearest_lower(*ReasoningEffort),
                usage_source=UsageSource.ANTHROPIC_OAUTH,
                plan_prompt_allowed=True,
            ),
            LlmProvider(
                id="openai",
                label="Codex (OpenAI)",
                oauth_provider="codex",
                effort_levels=_nearest_lower(_E.LOW, _E.MEDIUM, _E.HIGH, _E.XHIGH),
                usage_source=UsageSource.OPENAI_WHAM,
                plan_prompt_allowed=True,
            ),
            LlmProvider(
                id="google",
                label="Antigravity (Google)",
                oauth_provider="antigravity",
                effort_levels=_nearest_lower(_E.LOW, _E.MEDIUM, _E.HIGH),
                usage_source=None,
                plan_prompt_allowed=False,
            ),
            LlmProvider(
                id="xai",
                label="Grok (xAI)",
                oauth_provider="xai",
                effort_levels=_nearest_lower(_E.LOW, _E.HIGH),
                usage_source=None,
                plan_prompt_allowed=False,
            ),
        )
    },
)


def get_provider(provider_id: str) -> LlmProvider:
    """Запись реестра; провайдер вне реестра — 422 (раздел 3.1, `llm_accounts.provider`)."""
    provider = PROVIDERS.get(provider_id)
    if provider is None:
        raise ValidationError(f"Неизвестный провайдер LLM-аккаунта: {provider_id}")
    return provider


def provider_effort(provider: LlmProvider, effort: ReasoningEffort) -> ReasoningEffort:
    """Уровень, который уходит провайдеру и пишется в `node_logs.reasoning_effort`."""
    return provider.effort_levels[effort]
