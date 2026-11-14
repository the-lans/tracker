"""
Действия GitHub Actions подключаются по полному SHA коммита с версией в
комментарии (раздел 20.7): тег можно перевесить, коммит — нет. Dependabot
обновляет SHA вместе с комментарием.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_WORKFLOWS = Path(__file__).resolve().parents[2] / ".github" / "workflows"
_USES = re.compile(r"^\s*-?\s*uses:\s*(?P<ref>\S+)(?P<comment>.*)$")
_PINNED = re.compile(r"^[\w.-]+/[\w./-]+@[0-9a-f]{40}$")
_VERSION_COMMENT = re.compile(r"^\s+# v\d+\.\d+\.\d+$")


def _uses_lines() -> list[tuple[str, str, str]]:
    found = []
    for workflow in sorted(_WORKFLOWS.glob("*.yml")):
        for line in workflow.read_text().splitlines():
            if match := _USES.match(line):
                found.append((workflow.name, match["ref"], match["comment"]))
    return found


class TestWorkflowPins:
    def test_workflows_use_actions(self) -> None:
        assert {name for name, _, _ in _uses_lines()} >= {"ci.yml", "deploy.yml", "security.yml"}

    @pytest.mark.parametrize(("workflow", "ref", "comment"), _uses_lines())
    def test_pinned_by_sha(self, workflow: str, ref: str, comment: str) -> None:
        assert _PINNED.match(ref), f"{workflow}: {ref}"
        assert _VERSION_COMMENT.match(comment), f"{workflow}: {ref}{comment}"
