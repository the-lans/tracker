import { screen } from "@testing-library/react";
import { describe, expect, vi } from "vitest";
import { TaskCategoryCard } from "@/components/tasks/TaskCategoryCard";
import { TaskStatus, type Task } from "@/lib/types";
import type { MockedApi } from "@/test/apiMock";
import { makeTask, makeTaskCategory } from "@/test/factories";
import { test } from "@/test/fixtures";
import { renderWithProviders } from "@/test/renderWithProviders";

function renderCard(api: MockedApi, task: Partial<Task> = {}) {
  api.respond("GET /task-categories", [makeTaskCategory({ id: "cat1", name: "Бэкенд" })]);
  const onUpdate = vi.fn();
  return {
    onUpdate,
    ...renderWithProviders(
      <TaskCategoryCard task={makeTask({ created_by: "author", ...task })} pending={false} onUpdate={onUpdate} />,
    ),
  };
}

describe("TaskCategoryCard", () => {
  test.for([
    { from: null, choice: "Бэкенд", sent: "cat1" },
    { from: "cat1", choice: "Без категории", sent: null },
  ])("«$choice» → category_id $sent", async ({ from, choice, sent }, { api }) => {
    const { user, onUpdate } = renderCard(api, { category_id: from, status: TaskStatus.DONE });

    await user.click(screen.getByRole("combobox", { name: "Категория" }));
    await user.click(await screen.findByRole("option", { name: choice }));

    expect(onUpdate).toHaveBeenCalledWith({ category_id: sent });
  });

  test("категории — автора задачи", async ({ api }) => {
    renderCard(api);

    await vi.waitFor(() =>
      expect(api.queriesOf("GET /task-categories")).toEqual([{ author_id: "author" }]),
    );
  });

  test.for([
    { status: TaskStatus.NEW, pipeline_id: null, fills: true },
    { status: TaskStatus.NEW, pipeline_id: "p1", fills: false },
    { status: TaskStatus.IN_PROGRESS, pipeline_id: null, fills: false },
  ])("$status, пайплайн $pipeline_id: подставит пайплайн — $fills", ({ status, pipeline_id, fills }, { api }) => {
    renderCard(api, { status, pipeline_id });

    expect(screen.queryByText(/подставит выбранная категория/) !== null).toBe(fills);
  });
});
