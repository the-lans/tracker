import { screen, waitFor } from "@testing-library/react";
import { describe, expect } from "vitest";
import { PipelineNodeActivity } from "@/components/nodes/PipelineNodeActivity";
import { usePipelineNodes } from "@/hooks/usePipelines";
import { makeNode } from "@/test/factories";
import { test } from "@/test/fixtures";
import { renderWithProviders } from "@/test/renderWithProviders";

function PipelineNodes() {
  const { data: nodes } = usePipelineNodes("p1");
  return nodes?.map((node) => <PipelineNodeActivity key={node.id} node={node} />);
}

describe("PipelineNodeActivity", () => {
  test.for([false, true])("изменяет активность, сохраняя ноду (is_skipped=%s)", async (isSkipped, { api }) => {
    let node = makeNode({ id: "n1", pipeline_id: "p1", is_skipped: isSkipped });
    api.respond("GET /pipelines/p1/nodes", () => [node]);
    api.respond("PATCH /nodes/n1", () => {
      node = { ...node, is_skipped: !isSkipped };
      return node;
    });
    const { user } = renderWithProviders(<PipelineNodes />);
    const checkbox = await screen.findByRole("checkbox", { name: "Активна по умолчанию: Реализация" });
    expect(checkbox).toHaveAttribute("aria-checked", String(!isSkipped));

    await user.click(checkbox);

    await waitFor(() => expect(checkbox).toHaveAttribute("aria-checked", String(isSkipped)));
    expect(api.mutations()).toEqual([
      { method: "PATCH", path: "/nodes/n1", body: { is_skipped: !isSkipped } },
    ]);
    expect(screen.getAllByRole("checkbox")).toHaveLength(1);
  });

  test("при ошибке активность не меняется и показана причина", async ({ api, toasts }) => {
    api.respond("GET /pipelines/p1/nodes", [makeNode({ id: "n1", is_skipped: false })]);
    api.respond("PATCH /nodes/n1", { error: { status: 500, message: "Ошибка сохранения" } });
    const { user } = renderWithProviders(<PipelineNodes />);
    const checkbox = await screen.findByRole("checkbox");

    await user.click(checkbox);

    await waitFor(() => expect(toasts.error).toHaveBeenCalledWith("Ошибка сохранения"));
    expect(checkbox).toBeChecked();
  });
});
