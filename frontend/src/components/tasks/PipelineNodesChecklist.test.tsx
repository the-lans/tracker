import { screen } from "@testing-library/react";
import { describe, expect, vi } from "vitest";
import { PipelineNodesChecklist } from "@/components/tasks/PipelineNodesChecklist";
import { NodeType, type NodeItem } from "@/lib/types";
import { makeNode } from "@/test/factories";
import { test } from "@/test/fixtures";
import { renderWithProviders } from "@/test/renderWithProviders";

const nodes = [
  makeNode({ id: "n1", name: "Анализ задачи", node_type: NodeType.PLAN_PROMPT }),
  makeNode({ id: "n2", name: "Тесты и линтеры", node_type: NodeType.SCRIPT }),
];

function renderChecklist({ disabled = false, enabled = new Set(["n1"]) } = {}) {
  const onToggle = vi.fn();
  const view = renderWithProviders(
    <PipelineNodesChecklist
      nodes={nodes}
      isEnabled={(node: NodeItem) => enabled.has(node.id)}
      disabled={disabled}
      onToggle={onToggle}
    />,
  );
  return { ...view, onToggle };
}

describe("PipelineNodesChecklist", () => {
  test("ноды идут в порядке пайплайна с типом", () => {
    renderChecklist();

    expect(screen.getAllByRole("checkbox").map((box) => box.getAttribute("aria-label"))).toEqual([
      "Включить ноду Анализ задачи",
      "Включить ноду Тесты и линтеры",
    ]);
    expect(screen.getByText("Скрипт")).toBeInTheDocument();
  });

  test.for([
    { name: "Анализ задачи", node: "n1", enabled: false },
    { name: "Тесты и линтеры", node: "n2", enabled: true },
  ])("клик по «$name» переключает в $enabled", async ({ name, node, enabled }) => {
    const { user, onToggle } = renderChecklist();

    await user.click(screen.getByRole("checkbox", { name: `Включить ноду ${name}` }));

    expect(onToggle).toHaveBeenCalledExactlyOnceWith(expect.objectContaining({ id: node }), enabled);
  });

  test("в заблокированном списке переключать нельзя", async () => {
    const { user, onToggle } = renderChecklist({ disabled: true });

    for (const box of screen.getAllByRole("checkbox")) {
      expect(box).toBeDisabled();
      await user.click(box);
    }
    expect(onToggle).not.toHaveBeenCalled();
  });
});
