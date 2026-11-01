"""Тесты `services/claude_config.py` (раздел 6.4 ТЗ)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from services.claude_config import ensure_history_retention, session_config_dir
from services.errors import ValidationError

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


class TestSessionConfigDir:
    def test_created_under_root(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CLAUDE_SESSIONS_ROOT", str(tmp_path / "sessions"))

        directory = session_config_dir("RR-12345")

        assert directory == tmp_path / "sessions" / "RR-12345"
        assert directory.is_dir()

    @pytest.mark.parametrize("code", ["../RR-1", "RR 1", ""])
    def test_unsafe_code_rejected(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        code: str,
    ) -> None:
        monkeypatch.setenv("CLAUDE_SESSIONS_ROOT", str(tmp_path / "sessions"))

        with pytest.raises(ValidationError):
            session_config_dir(code)

        assert not (tmp_path / "sessions").exists()
