import { screen } from "@testing-library/react";
import { describe, expect } from "vitest";
import { EventsPage } from "@/pages/EventsPage";
import { EVENTS_PAGE_SIZE } from "@/hooks/useEvents";
import { EventAudience, EventCategory, type TrackerEvent } from "@/lib/events.types";
import { UserRole } from "@/lib/types";
import { makeCurrentUser } from "@/test/factories";
import { test } from "@/test/fixtures";
import { renderWithProviders } from "@/test/renderWithProviders";

function makeEvent(overrides: Partial<TrackerEvent> = {}): TrackerEvent {
  return {
    id: "e1",
    created_at: "2026-11-12T07:00:00Z",
    audience: EventAudience.USER,
    category: EventCategory.TASK,
    event_type: "done",
    title: "Задача выполнена",
    body: "RR-1: Обновить зависимости",
    task_id: "t1",
    ...overrides,
  };
}

describe("EventsPage", () => {
  test("свои события со ссылкой на задачу; вкладок для пользователя нет", async ({ api }) => {
    api.respond("GET /events", [makeEvent()]);
    renderWithProviders(<EventsPage />);

    expect(await screen.findByText("Задача выполнена")).toBeInTheDocument();
    expect(screen.getByText("RR-1: Обновить зависимости")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Открыть задачу" })).toHaveAttribute("href", "/tasks/t1");
    expect(screen.queryByRole("tab", { name: "Системные" })).not.toBeInTheDocument();
    expect(api.queriesOf("GET /events")[0]).toMatchObject({ audience: "user" });
  });

  test("администратор видит системную ленту", async ({ api }) => {
    api.respond("GET /events", [
      makeEvent({ audience: EventAudience.ADMINS, category: EventCategory.BACKUP, title: "Резервная копия проверена", task_id: null }),
    ]);
    const { user } = renderWithProviders(<EventsPage />, {
      currentUser: makeCurrentUser({ role: UserRole.ADMIN }),
    });

    await user.click(screen.getByRole("tab", { name: "Системные" }));

    await expect
      .poll(() => api.queriesOf("GET /events").map((query) => query.audience))
      .toContain("admins");
  });

  test("фильтр категории уходит в запрос", async ({ api }) => {
    const { user } = renderWithProviders(<EventsPage />);

    await user.click(await screen.findByRole("combobox", { name: "Категория" }));
    await user.click(await screen.findByRole("option", { name: "LLM-аккаунты" }));

    await expect
      .poll(() => api.queriesOf("GET /events").at(-1))
      .toMatchObject({ category: "llm_account" });
  });

  test.for([
    { count: EVENTS_PAGE_SIZE, more: true },
    { count: EVENTS_PAGE_SIZE - 1, more: false },
  ])("страница из $count событий → «Показать ещё»: $more", async ({ count, more }, { api }) => {
    const events = Array.from({ length: count }, (_, index) =>
      makeEvent({ id: `e${index}`, created_at: `2026-11-12T07:${String(59 - index).padStart(2, "0")}:00Z` }),
    );
    api.respond("GET /events", events);
    const { user } = renderWithProviders(<EventsPage />);

    await screen.findAllByText("Задача выполнена");

    expect(screen.queryByRole("button", { name: "Показать ещё" }) !== null).toBe(more);
    if (more) {
      await user.click(screen.getByRole("button", { name: "Показать ещё" }));
      await expect
        .poll(() => api.queriesOf("GET /events").at(-1))
        .toMatchObject({ before: events.at(-1)?.created_at });
    }
  });

  test("пустая лента — подсказка", async () => {
    renderWithProviders(<EventsPage />);

    expect(await screen.findByText("Событий нет")).toBeInTheDocument();
  });
});
