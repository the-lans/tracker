import { screen } from "@testing-library/react";
import { describe, expect } from "vitest";
import { TaskLifecycleActions } from "@/components/tasks/TaskLifecycleActions";
import { TaskStatus } from "@/lib/types";
import { makeTask } from "@/test/factories";
import { test } from "@/test/fixtures";
import { renderWithProviders } from "@/test/renderWithProviders";

const ACTIONS = ["Очистить контекст", "Очистить репозитории", "Дублировать"];

function shownActions(): string[] {
  return ACTIONS.filter((name) => screen.queryByRole("button", { name }) !== null);
}

describe("TaskLifecycleActions", () => {
  test.for([
    { status: TaskStatus.IN_PROGRESS, from: null, actions: [] },
    { status: TaskStatus.FAILED, from: null, actions: ["Очистить контекст", "Очистить репозитории"] },
    { status: TaskStatus.DONE, from: null, actions: ["Очистить репозитории", "Дублировать"] },
    { status: TaskStatus.ARCHIVED, from: TaskStatus.DONE, actions: ["Очистить репозитории", "Дублировать"] },
    { status: TaskStatus.ARCHIVED, from: TaskStatus.FAILED, actions: ["Очистить репозитории"] },
  ])("$status из $from → $actions", ({ status, from, actions }) => {
    renderWithProviders(<TaskLifecycleActions task={makeTask({ status, archived_from_status: from })} />);

    expect(shownActions()).toEqual(actions);
  });

  test("репозитории архивной задачи уже очищены — вместо кнопки подпись", () => {
    const task = makeTask({ status: TaskStatus.ARCHIVED, repo_cleaned_at: "2026-03-01T00:00:00Z" });
    renderWithProviders(<TaskLifecycleActions task={task} />);

    expect(screen.queryByRole("button", { name: "Очистить репозитории" })).not.toBeInTheDocument();
    expect(screen.getByText("Репозитории очищены")).toBeInTheDocument();
  });
});
