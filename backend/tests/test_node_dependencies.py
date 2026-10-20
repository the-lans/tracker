"""Тесты `services/node_dependencies.py` (раздел 13.3, 15.2 ТЗ)."""

from __future__ import annotations

import uuid

import pytest

from db.models.enums import NodeType
from services.node_dependencies import PipelineNodeRef, find_dependent_nodes


def _node(
    order_index: int,
    node_type: NodeType,
    prompt_template: str | None = None,
    *,
    is_enabled: bool = True,
    llm_output_last_n: int | None = None,
) -> PipelineNodeRef:
    return PipelineNodeRef(
        node_id=uuid.uuid4(),
        name=f"node-{order_index}",
        order_index=order_index,
        node_type=node_type,
        prompt_template=prompt_template,
        llm_output_last_n=llm_output_last_n,
        is_enabled=is_enabled,
    )


def _dependent_names(nodes: list[PipelineNodeRef], target: PipelineNodeRef) -> list[str]:
    return [node.name for node in find_dependent_nodes(nodes, target.node_id)]


class TestFindDependentNodes:
    def test_reference_to_nearest_source(self) -> None:
        script = _node(0, NodeType.SCRIPT)
        consumer = _node(1, NodeType.PLAIN_PROMPT, "Разбери {{node.script_output}}")

        assert _dependent_names([script, consumer], script) == ["node-1"]

    def test_closer_source_shadows_target(self) -> None:
        first = _node(0, NodeType.SCRIPT)
        second = _node(1, NodeType.SCRIPT)
        consumer = _node(2, NodeType.PLAIN_PROMPT, "{{node.script_output}}")

        assert _dependent_names([first, second, consumer], first) == []
        assert _dependent_names([first, second, consumer], second) == ["node-2"]

    def test_disabled_closer_source_does_not_shadow(self) -> None:
        first = _node(0, NodeType.SCRIPT)
        disabled = _node(1, NodeType.SCRIPT, is_enabled=False)
        consumer = _node(2, NodeType.PLAIN_PROMPT, "{{node.script_output}}")

        assert _dependent_names([first, disabled, consumer], first) == ["node-2"]

    @pytest.mark.parametrize(
        ("source_type", "variable", "expected"),
        [
            (NodeType.PLAN_PROMPT, "{{node.plan_text}}", ["node-1"]),
            (NodeType.SCRIPT, "{{node.llm_output}}", []),
            (NodeType.SLASH_COMMAND, "{{node.llm_output}}", ["node-1"]),
            (NodeType.PLAIN_PROMPT, "{{task.code}}", []),
        ],
        ids=["plan_text", "wrong_type", "llm_output", "no_node_variable"],
    )
    def test_source_type(
        self,
        source_type: NodeType,
        variable: str,
        expected: list[str],
    ) -> None:
        source = _node(0, source_type)
        consumer = _node(1, NodeType.PLAIN_PROMPT, variable)

        assert _dependent_names([source, consumer], source) == expected

    def test_llm_output_last_n_window(self) -> None:
        outside = _node(0, NodeType.PLAIN_PROMPT)
        inside = _node(1, NodeType.PLAIN_PROMPT)
        consumer = _node(
            2,
            NodeType.PLAIN_PROMPT,
            "{{node.llm_output_last_n}}",
            llm_output_last_n=1,
        )

        assert _dependent_names([outside, inside, consumer], outside) == []
        assert _dependent_names([outside, inside, consumer], inside) == ["node-2"]

    def test_disabled_consumer_ignored(self) -> None:
        script = _node(0, NodeType.SCRIPT)
        consumer = _node(1, NodeType.PLAIN_PROMPT, "{{node.script_output}}", is_enabled=False)

        assert _dependent_names([script, consumer], script) == []

    def test_unknown_target(self) -> None:
        script = _node(0, NodeType.SCRIPT)

        assert find_dependent_nodes([script], uuid.uuid4()) == []
