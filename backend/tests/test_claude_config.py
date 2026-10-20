"""Тесты `services/claude_config.py` (раздел 6.4 ТЗ)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from services.claude_config import ensure_history_retention

if TYPE_CHECKING:
    from pathlib import Path

_DAYS = 36500


def _settings(config_dir: Path) -> object:
    return json.loads((config_dir / "settings.json").read_text())


class TestEnsureHistoryRetention:
    def test_creates_settings(self, tmp_path: Path) -> None:
        ensure_history_retention(str(tmp_path / "account"), days=_DAYS)

        assert _settings(tmp_path / "account") == {"cleanupPeriodDays": _DAYS}

    @pytest.mark.parametrize(
        ("existing", "expected"),
        [
            (
                {"model": "opus", "cleanupPeriodDays": 30},
                {"model": "opus", "cleanupPeriodDays": _DAYS},
            ),
            ({"cleanupPeriodDays": 99999}, {"cleanupPeriodDays": 99999}),
        ],
        ids=["raises_short_period_keeps_other_keys", "keeps_longer_period"],
    )
    def test_existing_settings(
        self,
        tmp_path: Path,
        existing: dict[str, object],
        expected: dict[str, object],
    ) -> None:
        (tmp_path / "settings.json").write_text(json.dumps(existing))

        ensure_history_retention(str(tmp_path), days=_DAYS)

        assert _settings(tmp_path) == expected

    def test_broken_file_untouched(self, tmp_path: Path) -> None:
        (tmp_path / "settings.json").write_text("{не json")

        ensure_history_retention(str(tmp_path), days=_DAYS)

        assert (tmp_path / "settings.json").read_text() == "{не json"

    def test_no_config_dir(self) -> None:
        ensure_history_retention("", days=_DAYS)
