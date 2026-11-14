import { screen, waitFor } from "@testing-library/react";
import { describe, expect } from "vitest";
import { PipelineNodePause } from "@/components/nodes/PipelineNodePause";
import { usePipelineNodes } from "@/hooks/usePipelines";
import { NodeType } from "@/lib/types";
import { makeNode } from "@/test/factories";
import { test } from "@/test/fixtures";
import { renderWithProviders } from "@/test/renderWithProviders";

function PipelineNodes() {
  const { data: nodes } = usePipelineNodes("p1");
  return nodes?.map((node) => <PipelineNodePause key={node.id} node={node} />);
}

describe("PipelineNodePause", () => {
  test.for([false, true])("переключает паузу (pause_after=%s)", async (pauseAfter, { api }) => {
    let node = makeNode({ id: "n1", pause_after: pauseAfter });
    api.respond("GET /pipelines/p1/nodes", () => [node]);
    api.respond("PATCH /nodes/n1", () => {
      node = { ...node, pause_after: !pauseAfter };
      return node;
    });
    const { user } = renderWithProviders(<PipelineNodes />);
    const button = await screen.findByRole("button", { name: "Пауза после ноды Реализация" });
    expect(button).toHaveAttribute("aria-pressed", String(pauseAfter));

    await user.click(button);

    await waitFor(() => expect(button).toHaveAttribute("aria-pressed", String(!pauseAfter)));
    expect(api.mutations()).toEqual([
      { method: "PATCH", path: "/nodes/n1", body: { pause_after: !pauseAfter } },
    ]);
  });

  test("для очистки контекста кнопки нет", ({ api }) => {
    renderWithProviders(<PipelineNodePause node={makeNode({ node_type: NodeType.CLEAR_CONTEXT })} />);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(api.mutations()).toEqual([]);
  });

  test("ошибка сохраняет прежний признак и отображается пользователю", async ({ api, toasts }) => {
    api.respond("GET /pipelines/p1/nodes", [makeNode({ id: "n1", pause_after: false })]);
    api.respond("PATCH /nodes/n1", { error: { status: 500, message: "Ошибка сохранения" } });
    const { user } = renderWithProviders(<PipelineNodes />);
    const button = await screen.findByRole("button");

    await user.click(button);

    await waitFor(() => expect(toasts.error).toHaveBeenCalledWith("Ошибка сохранения"));
    expect(button).toHaveAttribute("aria-pressed", "false");
  });
});
