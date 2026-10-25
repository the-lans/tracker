import { screen } from "@testing-library/react";
import { describe, expect } from "vitest";
import { PeriodicScheduleEditor } from "@/components/admin/PeriodicScheduleEditor";
import { PeriodicScheduleType, type PeriodicTask } from "@/lib/types";
import { test } from "@/test/fixtures";
import { renderWithProviders } from "@/test/renderWithProviders";

function makePeriodicTask(overrides: Partial<PeriodicTask> = {}): PeriodicTask {
  return {
    id: "pt1",
    name: "sync_gitlab_mr_statuses",
    display_name: "Статусы MR в GitLab",
    description: "",
    task_path: "tasks.periodic.sync_gitlab_mr_statuses",
    schedule_type: PeriodicScheduleType.INTERVAL,
    interval_seconds: 300,
    crontab_expression: null,
    is_enabled: true,
    last_run_at: null,
    last_run_status: null,
    next_run_at: null,
    ...overrides,
  };
}

const cronTask = makePeriodicTask({
  schedule_type: PeriodicScheduleType.CRONTAB,
  interval_seconds: null,
  crontab_expression: "0 3 * * *",
});

async function startEditing(task: PeriodicTask) {
  const view = renderWithProviders(<PeriodicScheduleEditor task={task} />);
  await view.user.click(screen.getByRole("button", { name: `Изменить расписание ${task.display_name}` }));
  const field = screen.getByRole("textbox");
  await view.user.clear(field);
  return { ...view, field };
}

const saveButton = () => screen.getByRole("button", { name: "Сохранить расписание" });

describe("PeriodicScheduleEditor", () => {
  test.for([
    { task: makePeriodicTask(), text: "каждые 5 минут" },
    { task: cronTask, text: "по расписанию cron: 0 3 * * *" },
  ])("показывает расписание: $text", ({ task, text }) => {
    renderWithProviders(<PeriodicScheduleEditor task={task} />);

    expect(screen.getByText(text)).toBeInTheDocument();
  });

  describe("интервал", () => {
    test.for(["", "0", "-60", "1.5", "пять", "   "])("«%s» сохранить нельзя", async (draft) => {
      const { user, field } = await startEditing(makePeriodicTask());

      if (draft) await user.type(field, draft);

      expect(saveButton()).toBeDisabled();
    });

    test("сохраняет интервал числом и закрывает редактор", async ({ api }) => {
      const { user, field } = await startEditing(makePeriodicTask());

      await user.type(field, " 600 ");
      await user.click(saveButton());

      expect(api.mutations()).toEqual([
        { method: "PATCH", path: "/periodic-tasks/pt1", body: { interval_seconds: 600 } },
      ]);
      await expect.poll(() => screen.queryByRole("textbox")).toBeNull();
    });
  });

  describe("cron", () => {
    test("пустое выражение сохранить нельзя", async () => {
      await startEditing(cronTask);

      expect(saveButton()).toBeDisabled();
    });

    test("ошибка сервера оставляет редактор открытым", async ({ api, toasts }) => {
      api.respond("PATCH /periodic-tasks/pt1", { error: { status: 422, message: "Неверное cron-выражение" } });
      const { user, field } = await startEditing(cronTask);

      await user.type(field, "0 3 * *");
      await user.click(saveButton());

      expect(api.mutations()[0].body).toEqual({ crontab_expression: "0 3 * *" });
      await expect.poll(() => toasts.error.mock.calls).toEqual([["Неверное cron-выражение"]]);
      expect(screen.getByRole("textbox")).toHaveValue("0 3 * *");
    });
  });

  test("отмена возвращает прежнее расписание без запроса", async ({ api }) => {
    const { user, field } = await startEditing(makePeriodicTask());

    await user.type(field, "60");
    await user.click(screen.getByRole("button", { name: "Отмена" }));

    expect(screen.getByText("каждые 5 минут")).toBeInTheDocument();
    expect(api.mutations()).toEqual([]);
  });
});
