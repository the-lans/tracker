import { screen } from "@testing-library/react";
import { describe, expect } from "vitest";
import { TaskDayMarks } from "@/components/tasks/TaskDayMarks";
import { TaskStatus } from "@/lib/types";
import type { MockedApi } from "@/test/apiMock";
import { makeDailyCalendar, makeTask } from "@/test/factories";
import { test } from "@/test/fixtures";
import { renderWithProviders } from "@/test/renderWithProviders";

function renderMarks(api: MockedApi, days: string[]) {
  api.respond("GET /daily/calendar", makeDailyCalendar());
  api.respond("GET /daily/marks", days.length ? [{ task_id: "t1", days }] : []);
  return renderWithProviders(<TaskDayMarks task={makeTask({ id: "t1" })} />);
}

describe("TaskDayMarks", () => {
  test.for([
    { name: "Сегодня", marked: [], request: { method: "PUT", path: "/tasks/t1/day-marks/2026-11-16" } },
    { name: "Завтра", marked: [], request: { method: "PUT", path: "/tasks/t1/day-marks/2026-11-17" } },
    {
      name: "Сегодня",
      marked: ["2026-11-16"],
      request: { method: "DELETE", path: "/tasks/t1/day-marks/2026-11-16" },
    },
  ])("«$name» при отметках $marked → $request.method", async ({ name, marked, request }, { api }) => {
    const { user } = renderMarks(api, marked);
    const chip = await screen.findByRole("button", { name, pressed: marked.length > 0 });

    await user.click(chip);

    expect(api.mutations()).toEqual([{ ...request, body: undefined }]);
  });

  test("вчерашняя отметка не нажимает «Сегодня»", async ({ api }) => {
    renderMarks(api, ["2026-11-15"]);

    expect(await screen.findByRole("button", { name: "Сегодня" })).toHaveAttribute("aria-pressed", "false");
  });

  test("у архивной задачи отметок нет", async ({ api }) => {
    api.respond("GET /daily/calendar", makeDailyCalendar());
    renderWithProviders(
      <>
        <TaskDayMarks task={makeTask({ id: "t1", status: TaskStatus.DONE })} />
        <TaskDayMarks task={makeTask({ id: "t2", status: TaskStatus.ARCHIVED })} />
      </>,
    );

    // Отметки обычной задачи появились — календарь загружен, архивная всё равно без них.
    await screen.findByRole("group", { name: "Отметить на день" });
    expect(screen.getAllByRole("group", { name: "Отметить на день" })).toHaveLength(1);
  });
});
