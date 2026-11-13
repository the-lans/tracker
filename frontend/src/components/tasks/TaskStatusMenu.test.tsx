import { screen, within } from "@testing-library/react";
import { describe, expect } from "vitest";
import { TaskStatusMenu } from "@/components/tasks/TaskStatusMenu";
import { TaskStatus, type Task } from "@/lib/types";
import { makeTask } from "@/test/factories";
import { test } from "@/test/fixtures";
import { renderWithProviders } from "@/test/renderWithProviders";

const MENU = { name: "Сменить статус задачи" };

function renderMenu(task: Partial<Task>) {
  return renderWithProviders(<TaskStatusMenu task={makeTask(task)} />);
}

describe("TaskStatusMenu", () => {
  test.for([
    { status: TaskStatus.IN_PROGRESS, chat_active: false },
    { status: TaskStatus.REFINING, chat_active: true },
  ])("$status, чат $chat_active — только бейдж", (fields) => {
    renderMenu(fields);

    expect(screen.queryByRole("combobox", MENU)).not.toBeInTheDocument();
  });

  test("до запуска — переход сразу", async ({ api, toasts }) => {
    const { user } = renderMenu({ status: TaskStatus.DEFINED });

    await user.click(screen.getByRole("combobox", MENU));
    await user.click(await screen.findByRole("option", { name: "Готова к реализации" }));

    expect(api.mutations()).toEqual([
      { method: "POST", path: "/tasks/t1/status", body: { to_status: TaskStatus.READY } },
    ]);
    expect(toasts.success).toHaveBeenCalledWith("Статус: «Готова к реализации»");
  });

  test.for([
    { status: TaskStatus.FAILED, confirm: true },
    { status: TaskStatus.DONE, confirm: false },
    { status: TaskStatus.ARCHIVED, confirm: true },
  ])("$status — сброс прогона после подтверждения ($confirm)", async ({ status, confirm }, { api }) => {
    const { user } = renderMenu({ status });

    await user.click(screen.getByRole("combobox", MENU));
    await user.click(await screen.findByRole("option", { name: "Сформулирована" }));
    expect(api.mutations()).toEqual([]);
    const dialog = screen.getByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: confirm ? "Сбросить прогон" : "Отмена" }));

    expect(api.mutations()).toEqual(
      confirm ? [{ method: "POST", path: "/tasks/t1/status", body: { to_status: TaskStatus.DEFINED } }] : [],
    );
  });
});
