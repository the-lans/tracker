import { screen } from "@testing-library/react";
import { describe, expect, vi } from "vitest";
import { PipelinePickerDialog } from "@/components/tasks/PipelinePickerDialog";
import { makeNode, makeTask } from "@/test/factories";
import { test } from "@/test/fixtures";
import { renderWithProviders } from "@/test/renderWithProviders";

describe("PipelinePickerDialog", () => {
  test("пайплайн выбирается в списке с подписью и привязывается к задаче", async ({ api }) => {
    api.respond("GET /pipelines", [
      { id: "p1", name: "Фича с тестами", is_archived: false, created_by: "u1" },
    ]);
    api.respond("GET /pipelines/p1/nodes", [makeNode({ id: "n1", pipeline_id: "p1" })]);
    const onOpenChange = vi.fn();
    const { user } = renderWithProviders(
      <PipelinePickerDialog task={makeTask({ id: "t1" })} open onOpenChange={onOpenChange} />,
    );

    await user.click(screen.getByRole("combobox", { name: "Пайплайн" }));
    await user.click(await screen.findByRole("option", { name: "Фича с тестами" }));
    await screen.findByText("Реализация");
    await user.click(screen.getByRole("button", { name: "Привязать" }));

    await vi.waitFor(() =>
      expect(api.mutations()).toEqual([
        { method: "POST", path: "/tasks/t1/pipeline", body: { pipeline_id: "p1", disabled_node_ids: [] } },
      ]),
    );
  });
});
