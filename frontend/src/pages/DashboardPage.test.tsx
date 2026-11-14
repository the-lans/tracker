import { screen } from "@testing-library/react";
import { describe, expect } from "vitest";
import { DashboardPage } from "@/pages/DashboardPage";
import { TaskStatus, type Task } from "@/lib/types";
import type { MockedApi } from "@/test/apiMock";
import { makeDailyCalendar, makeTask, makeTaskCategory } from "@/test/factories";
import { test } from "@/test/fixtures";
import { renderWithProviders } from "@/test/renderWithProviders";

/** По задаче в каждом статусе дашборда (архивные сервер не отдаёт): код — `RR-<статус>`. */
const tasksByStatus: Task[] = Object.values(TaskStatus)
  .filter((status) => status !== TaskStatus.ARCHIVED)
  .map((status, index) =>
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

  describe("фильтр по категории", () => {
    const categorized: Task[] = [
      makeTask({ id: "c1", code: "RR-back", status: TaskStatus.NEW, category_id: "back" }),
      makeTask({ id: "c2", code: "RR-front", status: TaskStatus.DONE, category_id: "front" }),
      makeTask({ id: "c3", code: "RR-plain", status: TaskStatus.NEW, category_id: null }),
    ];

    function renderWithCategories(api: MockedApi) {
      api.respond("GET /task-categories", [
        makeTaskCategory({ id: "back", name: "Бэкенд" }),
        makeTaskCategory({ id: "front", name: "Фронтенд" }),
      ]);
      return renderDashboard(api, categorized);
    }

    test.for([
      { option: "Бэкенд", codes: ["RR-back"] },
      { option: "Без категории", codes: ["RR-plain"] },
      { option: "Все категории", codes: ["RR-back", "RR-front", "RR-plain"] },
    ])("«$option» → $codes", async ({ option, codes }, { api }) => {
      const { user } = renderWithCategories(api);
      await screen.findByText("RR-back");

      await user.click(screen.getByRole("combobox", { name: "Категория" }));
      await user.click(await screen.findByRole("option", { name: option }));

      expect(shownCodes().sort()).toEqual([...codes].sort());
    });

    test("счётчики статусов — внутри выбранной категории", async ({ api }) => {
      const { user } = renderWithCategories(api);
      await screen.findByText("RR-back");

      await user.click(screen.getByRole("combobox", { name: "Категория" }));
      await user.click(await screen.findByRole("option", { name: "Фронтенд" }));

      expect(screen.getByRole("button", { name: "Все · 1" })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Завершено · 1" })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "До запуска · 0" })).toBeInTheDocument();
    });
  });

  describe("фильтр по отметкам на день", () => {
    const marked: Task[] = [
      makeTask({ id: "m1", code: "RR-today", status: TaskStatus.NEW }),
      makeTask({ id: "m2", code: "RR-both", status: TaskStatus.DONE }),
      makeTask({ id: "m3", code: "RR-none", status: TaskStatus.NEW }),
    ];

    test.for([
      { option: "Вчера", codes: ["RR-both"] },
      { option: "Сегодня", codes: ["RR-today"] },
      { option: "Завтра", codes: ["RR-both"] },
      { option: "Все дни", codes: ["RR-today", "RR-both", "RR-none"] },
    ])("«$option» → $codes", async ({ option, codes }, { api }) => {
      api.respond("GET /daily/calendar", makeDailyCalendar());
      api.respond("GET /daily/marks", [
        { task_id: "m1", days: ["2026-11-16"] },
        { task_id: "m2", days: ["2026-11-15", "2026-11-17"] },
      ]);
      const { user } = renderDashboard(api, marked);
      await screen.findByText("RR-none");

      await user.click(screen.getByRole("combobox", { name: "Отмечены на день" }));
      await user.click(await screen.findByRole("option", { name: option }));

      expect(shownCodes().sort()).toEqual([...codes].sort());
      expect(screen.getByRole("button", { name: `Все · ${codes.length}`, pressed: true })).toBeInTheDocument();
    });
  });
});
