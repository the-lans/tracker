import { fireEvent, screen, within } from "@testing-library/react";
import { describe, expect } from "vitest";
import { DayHistoryTab } from "@/components/daily/DayHistoryTab";
import type { MockedApi } from "@/test/apiMock";
import { makeDailyCalendar, makeDailyEvent, makeDailyMarkedTask } from "@/test/factories";
import { test } from "@/test/fixtures";
import { renderWithProviders } from "@/test/renderWithProviders";

const CALENDAR = makeDailyCalendar();

function renderHistory(api: MockedApi) {
  api.respond("GET /daily/days/2026-11-16", {
    day: "2026-11-16",
    tasks: [
      makeDailyMarkedTask({ id: "t1", code: "RR-1", fact: "done" }),
      makeDailyMarkedTask({ id: "t2", code: "RR-2", fact: "no_work" }),
    ],
    events: [
      makeDailyEvent({ id: "e1", title: "Ревью кода", start_time: "10:00:00", end_time: "11:00:00" }),
      makeDailyEvent({ id: "e2", source: "google", title: "Backend Sprint" }),
    ],
  });
  api.respond("GET /daily/days/2026-11-15", { day: "2026-11-15", tasks: [], events: [] });
  return renderWithProviders(<DayHistoryTab calendar={CALENDAR} />);
}

describe("DayHistoryTab", () => {
  test("задачи дня с итогом и события по времени", async ({ api }) => {
    renderHistory(api);

    const task = (await screen.findByText("RR-1")).closest("li");
    expect(task && within(task).getByText("завершена")).toBeInTheDocument();
    expect(screen.getByText("без работы")).toBeInTheDocument();
    expect(screen.getByText("10:00–11:00")).toBeInTheDocument();
    expect(screen.getByText("весь день")).toBeInTheDocument();
  });

  test("дни — от завтра до 7 дней назад, выбор дня загружает его", async ({ api }) => {
    const { user } = renderHistory(api);
    await screen.findByText("RR-1");

    const days = within(screen.getByRole("tablist", { name: "День" })).getAllByRole("tab");
    expect(days.map((tab) => tab.textContent).slice(0, 5)).toEqual([
      "Завтра",
      "Сегодня",
      "Вчера",
      "Позавчера",
      "13.11, пт",
    ]);
    await user.click(screen.getByRole("tab", { name: "Вчера" }));

    expect(await screen.findByText("Задач на этот день не отмечено")).toBeInTheDocument();
  });

  test.for([
    { title: "Ревью кода", edit: true, hide: false },
    { title: "Backend Sprint", edit: false, hide: true },
  ])("«$title»: правка $edit, скрытие $hide", async ({ title, edit, hide }, { api }) => {
    renderHistory(api);
    await screen.findByText(title);

    expect(screen.queryByRole("button", { name: `Изменить ${title}` }) !== null).toBe(edit);
    expect(screen.queryByRole("button", { name: `Удалить ${title}` }) !== null).toBe(edit);
    expect(screen.queryByRole("button", { name: `Скрыть ${title}` }) !== null).toBe(hide);
  });

  test("событие календаря скрывается", async ({ api }) => {
    const { user } = renderHistory(api);

    await user.click(await screen.findByRole("button", { name: "Скрыть Backend Sprint" }));

    expect(api.mutations()).toEqual([
      { method: "PUT", path: "/daily/events/e2/hidden", body: { hidden: true } },
    ]);
  });

  test("новое событие — на выбранный день, время по Москве", async ({ api }) => {
    const { user } = renderHistory(api);
    await user.click(await screen.findByRole("button", { name: "Событие" }));

    await user.type(screen.getByLabelText("Название"), "Выкатка релиза");
    fireEvent.change(screen.getByLabelText("Начало, МСК"), { target: { value: "15:00" } });
    await user.click(screen.getByRole("button", { name: "Добавить" }));

    expect(api.mutations()).toEqual([
      {
        method: "POST",
        path: "/daily/events",
        body: { day: "2026-11-16", title: "Выкатка релиза", notes: null, start_time: "15:00:00", end_time: null },
      },
    ]);
  });

  test("конец без начала — сохранить нельзя", async ({ api }) => {
    const { user } = renderHistory(api);
    await user.click(await screen.findByRole("button", { name: "Событие" }));

    await user.type(screen.getByLabelText("Название"), "Созвон");
    fireEvent.change(screen.getByLabelText("Конец, МСК"), { target: { value: "12:00" } });

    expect(screen.getByText("Укажите начало события или очистите конец")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Добавить" })).toBeDisabled();
  });
});
