import { screen } from "@testing-library/react";
import { describe, expect } from "vitest";
import { DashboardPage } from "@/pages/DashboardPage";
import { TaskStatus, type Task } from "@/lib/types";
import type { MockedApi } from "@/test/apiMock";
import { makeTask } from "@/test/factories";
import { test } from "@/test/fixtures";
import { renderWithProviders } from "@/test/renderWithProviders";

/** По задаче в каждом статусе: код — `RR-<статус>`. */
const tasksByStatus: Task[] = Object.values(TaskStatus).map((status, index) =>
  makeTask({ id: `t${index}`, code: `RR-${status}`, title: `Задача ${status}`, status }),
);

function renderDashboard(api: MockedApi, tasks: Task[] = tasksByStatus) {
  api.respond("GET /tasks", tasks);
  api.respond("GET /tasks/awaiting-count", { count: 0 });
  api.respond("GET /tasks/queue-summary", { max_parallel_tasks: 3, occupied: 2, ready: 4, night_worker: 1 });
  return renderWithProviders(<DashboardPage />);
}

/** Коды задач на карточках — в порядке показа. */
const shownCodes = () => screen.queryAllByRole("link", { name: /^RR-/ }).map((link) => link.textContent);

const search = () => screen.getByRole("textbox", { name: "Найти задачу по коду или названию" });

describe("DashboardPage", () => {
  describe("фильтры по статусу", () => {
    test("счётчики считают каждую группу статусов", async ({ api }) => {
      renderDashboard(api);

      expect(await screen.findByRole("button", { name: "Все · 14" })).toBeInTheDocument();
      for (const name of [
        "До запуска · 5",
        "В очереди · 2",
        "В работе · 3",
        "Ждут решения · 2",
        "Завершено · 1",
        "Ошибки · 2",
      ]) {
        expect(screen.getByRole("button", { name })).toBeInTheDocument();
      }
    });

    test.for([
      { filter: "До запуска", codes: ["RR-new", "RR-refining", "RR-defined", "RR-ready", "RR-night_worker"] },
      { filter: "В очереди", codes: ["RR-ready", "RR-night_worker"] },
      { filter: "В работе", codes: ["RR-in_progress", "RR-paused", "RR-awaiting_limit"] },
      { filter: "Ждут решения", codes: ["RR-plan_review", "RR-awaiting_input"] },
      { filter: "Завершено", codes: ["RR-done"] },
      { filter: "Ошибки", codes: ["RR-rebase_conflict", "RR-failed"] },
    ])("«$filter» → $codes", async ({ filter, codes }, { api }) => {
      const { user } = renderDashboard(api);

      await user.click(await screen.findByRole("button", { name: new RegExp(`^${filter} ·`) }));

      expect(shownCodes().sort()).toEqual([...codes].sort());
    });

    test("«Все» возвращает и новые, и запланированные задачи", async ({ api }) => {
      const { user } = renderDashboard(api);

      await user.click(await screen.findByRole("button", { name: /^Завершено ·/ }));
      await user.click(screen.getByRole("button", { name: /^Все ·/ }));

      expect(shownCodes()).toHaveLength(tasksByStatus.length);
      expect(shownCodes()).toEqual(expect.arrayContaining(["RR-new", "RR-queued"]));
    });
  });

  describe("поиск", () => {
    const tasks = [
      makeTask({ id: "t1", code: "RR-12345", title: "Экспорт отчётов в CSV", status: TaskStatus.DONE }),
      makeTask({ id: "t2", code: "RR-12370", title: "Фильтр по датам", status: TaskStatus.IN_PROGRESS }),
      makeTask({ id: "t3", code: "SHOP-7", title: "Экспорт заказов", status: TaskStatus.IN_PROGRESS }),
    ];

    test.for([
      { query: "rr-1237", codes: ["RR-12370"] },
      { query: "  ЭКСПОРТ ", codes: ["RR-12345", "SHOP-7"] },
      { query: "shop", codes: ["SHOP-7"] },
    ])("«$query» → $codes", async ({ query, codes }, { api }) => {
      const { user } = renderDashboard(api, tasks);
      await screen.findByText("RR-12345");

      await user.type(search(), query);

      expect(screen.queryAllByRole("link", { name: /^(RR|SHOP)-/ }).map((link) => link.textContent)).toEqual(codes);
    });

    test("поиск работает внутри выбранного фильтра", async ({ api }) => {
      const { user } = renderDashboard(api, tasks);

      await user.click(await screen.findByRole("button", { name: /^В работе ·/ }));
      await user.type(search(), "экспорт");

      expect(screen.queryAllByRole("link", { name: /^(RR|SHOP)-/ }).map((link) => link.textContent)).toEqual([
        "SHOP-7",
      ]);
    });

    test("ничего не нашлось — подсказка сбросить фильтр", async ({ api }) => {
      const { user } = renderDashboard(api, tasks);
      await screen.findByText("RR-12345");

      await user.type(search(), "RR-99999");

      expect(screen.getByText("Задачи не найдены")).toBeInTheDocument();
    });
  });

  test("слоты и очередь пользователя — над списком", async ({ api }) => {
    renderDashboard(api);

    expect(await screen.findByText("Слоты: 2 из 3 · в очереди 4 · ночью 1")).toBeInTheDocument();
  });

  test("без задач — подсказка, как создать первую", async ({ api }) => {
    renderDashboard(api, []);

    expect(await screen.findByText("Задач пока нет")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Все · 0" })).toBeInTheDocument();
  });
});
