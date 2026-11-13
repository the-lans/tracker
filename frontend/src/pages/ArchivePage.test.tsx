import { screen, waitFor, within } from "@testing-library/react";
import { describe, expect } from "vitest";
import { ArchivePage } from "@/pages/ArchivePage";
import type { ArchivedTask, ArchivedTaskPage } from "@/lib/archive.types";
import { TaskStatus, UserRole } from "@/lib/types";
import type { MockedApi, MockResponse } from "@/test/apiMock";
import { makeCurrentUser, makeUser } from "@/test/factories";
import { test } from "@/test/fixtures";
import { renderWithProviders } from "@/test/renderWithProviders";

function makeArchivedTask(overrides: Partial<ArchivedTask> = {}): ArchivedTask {
  return {
    id: "a1",
    code: "RR-100",
    title: "Отчёт по продажам",
    archived_from_status: TaskStatus.DONE,
    category_name: null,
    finished_at: "2026-03-01T10:00:00Z",
    archived_at: "2026-03-15T10:00:00Z",
    repo_cleaned_at: null,
    created_by: "u1",
    ...overrides,
  };
}

function page(items: ArchivedTask[], total = items.length, pageNumber = 1): ArchivedTaskPage {
  return { items, total, page: pageNumber, page_size: 20 };
}

function renderArchive(
  api: MockedApi,
  response: MockResponse = page([makeArchivedTask()]),
  { path = "/archive", archiveAfterDays = 14 as number | null } = {},
) {
  api.respond("GET /tasks/archive", response);
  api.respond("GET /profile", makeUser({ archive_after_days: archiveAfterDays }));
  return renderWithProviders(<ArchivePage />, { path });
}

const archiveQueries = (api: MockedApi) => api.queriesOf("GET /tasks/archive");
const search = () => screen.getByRole("searchbox", { name: "Найти задачу по коду или названию" });

describe("ArchivePage", () => {
  test("строка — ссылка на задачу с итоговым статусом, категорией и датой", async ({ api }) => {
    renderArchive(api, page([makeArchivedTask({ category_name: "Бэкенд", repo_cleaned_at: "2026-03-20T00:00:00Z" })]));

    const row = await screen.findByRole("link", { name: "RR-100 · Отчёт по продажам" });
    expect(row).toHaveAttribute("href", "/tasks/a1");
    expect(within(row).getByText("Готово")).toBeInTheDocument();
    expect(within(row).getByText("Бэкенд")).toBeInTheDocument();
    expect(within(row).getByText("Репозитории очищены")).toBeInTheDocument();
    expect(screen.getByText("1 задача")).toBeInTheDocument();
  });

  test.for([
    { from: TaskStatus.FAILED, badge: "Ошибка" },
    { from: null, badge: "Архив" },
  ])("итоговый статус $from → «$badge»", async ({ from, badge }, { api }) => {
    renderArchive(api, page([makeArchivedTask({ archived_from_status: from })]));

    const row = await screen.findByRole("link", { name: /RR-100/ });
    expect(within(row).getByText(badge)).toBeInTheDocument();
  });

  test("поиск уходит в запрос после паузы, одним запросом", async ({ api }) => {
    const { user } = renderArchive(api);
    await screen.findByRole("link", { name: /RR-100/ });

    await user.type(search(), "отчёт");

    await waitFor(() => expect(archiveQueries(api).at(-1)).toMatchObject({ search: "отчёт" }));
    expect(archiveQueries(api).filter((query) => query.search !== undefined)).toEqual([
      { search: "отчёт", page: "1", page_size: "20" },
    ]);
  });

  test("даты — границы локальных суток, смена отбора возвращает на первую страницу", async ({ api }) => {
    const { user } = renderArchive(api, page([makeArchivedTask()], 45, 2), { path: "/archive?page=2" });
    await screen.findByText("Страница 2 из 3");

    await user.type(screen.getByLabelText("Завершена с"), "2026-03-01");
    await user.type(screen.getByLabelText("по"), "2026-03-31");

    await waitFor(() =>
      expect(archiveQueries(api).at(-1)).toEqual({
        finished_from: new Date("2026-03-01T00:00:00").toISOString(),
        finished_to: new Date("2026-04-01T00:00:00").toISOString(),
        page: "1",
        page_size: "20",
      }),
    );
  });

  test("фильтры берутся из адреса, «Сбросить» их очищает", async ({ api }) => {
    const { user } = renderArchive(api, page([makeArchivedTask()]), {
      path: "/archive?q=RR-1&from=2026-03-01",
    });

    expect(search()).toHaveValue("RR-1");
    expect(screen.getByLabelText("Завершена с")).toHaveValue("2026-03-01");
    await waitFor(() => expect(archiveQueries(api)[0]).toMatchObject({ search: "RR-1" }));

    await user.click(screen.getByRole("button", { name: "Сбросить" }));

    expect(search()).toHaveValue("");
    await waitFor(() => expect(archiveQueries(api).at(-1)).toEqual({ page: "1", page_size: "20" }));
    expect(screen.queryByRole("button", { name: "Сбросить" })).not.toBeInTheDocument();
  });

  test("листание запрашивает следующую страницу", async ({ api }) => {
    const { user } = renderArchive(api, page([makeArchivedTask()], 45));
    await screen.findByText("Страница 1 из 3");

    await user.click(screen.getByRole("button", { name: "Следующая страница" }));

    await waitFor(() => expect(archiveQueries(api).at(-1)).toMatchObject({ page: "2" }));
  });

  test("страница за концом списка — переход на последнюю", async ({ api }) => {
    renderArchive(api, page([], 25, 9), { path: "/archive?page=9" });

    await waitFor(() => expect(archiveQueries(api).at(-1)).toMatchObject({ page: "2" }));
  });

  test.for([
    { days: 14, path: "/archive", title: "В архиве пусто", hint: "через 14 дней после завершения" },
    { days: 1, path: "/archive", title: "В архиве пусто", hint: "через 1 день после завершения" },
    { days: null, path: "/archive", title: "В архиве пусто", hint: "Автоархивация выключена" },
    { days: 14, path: "/archive?q=нет", title: "Ничего не найдено", hint: "Измените поиск или период." },
  ])("пусто ($path, N = $days) → «$title»", async ({ days, path, title, hint }, { api }) => {
    renderArchive(api, page([]), { path, archiveAfterDays: days });

    expect(await screen.findByText(title)).toBeInTheDocument();
    expect(await screen.findByText(new RegExp(hint))).toBeInTheDocument();
    expect(screen.queryByRole("navigation", { name: "Страницы" })).not.toBeInTheDocument();
  });

  test("администратор видит автора чужой задачи", async ({ api }) => {
    api.respond("GET /users", [makeUser({ id: "u9", email: "boris@example.com" })]);
    api.respond("GET /tasks/archive", page([makeArchivedTask({ created_by: "u9" })]));
    api.respond("GET /profile", makeUser());
    renderWithProviders(<ArchivePage />, {
      path: "/archive",
      currentUser: makeCurrentUser({ role: UserRole.ADMIN }),
    });

    expect(await screen.findByText("Автор: boris@example.com")).toBeInTheDocument();
  });

  test("сбой загрузки — сообщение об ошибке", async ({ api }) => {
    renderArchive(api, { error: { status: 500, message: "fail" } });

    expect(await screen.findByText("Не удалось загрузить архив")).toBeInTheDocument();
  });
});
