"""Реестр провайдеров LLM-аккаунтов (раздел 19.7 ТЗ)."""

from __future__ import annotations

import pytest

from db.models.enums import ReasoningEffort
from services.errors import ValidationError
from services.llm_providers import PROVIDERS, UsageSource, get_provider, provider_effort

_E = ReasoningEffort


class TestRegistry:
    @pytest.mark.parametrize(
        ("provider_id", "oauth_provider", "usage_source", "plan_prompt_allowed"),
        [
            ("anthropic", "claude", UsageSource.ANTHROPIC_OAUTH, True),
            ("openai", "codex", UsageSource.OPENAI_WHAM, True),
            ("google", "antigravity", None, False),
            ("xai", "xai", None, False),
        ],
    )
    def test_entries(
        self,
        provider_id: str,
        oauth_provider: str,
        usage_source: UsageSource | None,
        plan_prompt_allowed: bool,
    ) -> None:
        provider = get_provider(provider_id)
        assert (provider.oauth_provider, provider.usage_source, provider.plan_prompt_allowed) == (
            oauth_provider,
            usage_source,
            plan_prompt_allowed,
        )

    def test_unknown_provider_rejected(self) -> None:
        with pytest.raises(ValidationError):
            get_provider("mistral")

    @pytest.mark.parametrize("provider_id", sorted(PROVIDERS))
    def test_every_level_translated(self, provider_id: str) -> None:
        assert set(PROVIDERS[provider_id].effort_levels) == set(ReasoningEffort)


class TestProviderEffort:
    @pytest.mark.parametrize(
        ("provider_id", "expected"),
        [
            ("anthropic", [_E.LOW, _E.MEDIUM, _E.HIGH, _E.XHIGH, _E.MAX]),
            ("openai", [_E.LOW, _E.MEDIUM, _E.HIGH, _E.XHIGH, _E.XHIGH]),
            ("google", [_E.LOW, _E.MEDIUM, _E.HIGH, _E.HIGH, _E.HIGH]),
            ("xai", [_E.LOW, _E.LOW, _E.HIGH, _E.HIGH, _E.HIGH]),
        ],
    )
    def test_scale(self, provider_id: str, expected: list[ReasoningEffort]) -> None:
        provider = get_provider(provider_id)
        assert [provider_effort(provider, effort) for effort in ReasoningEffort] == expected
