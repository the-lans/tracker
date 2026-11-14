import { screen } from "@testing-library/react";
import { describe, expect, vi } from "vitest";
import { GoogleCalendarCard } from "@/components/profile/GoogleCalendarCard";
import type { MockedApi } from "@/test/apiMock";
import { makeGoogleCalendarConnection } from "@/test/factories";
import { test } from "@/test/fixtures";
import { renderWithProviders } from "@/test/renderWithProviders";

const CALENDARS = [
  { id: "primary", summary: "Основной", primary: true },
  { id: "team@group.calendar.google.com", summary: "Команда", primary: false },
];

function renderCard(api: MockedApi, connection: unknown, path = "/profile") {
  api.respond("GET /profile/google-calendar", connection);
  api.respond("GET /profile/google-calendar/calendars", CALENDARS);
  return renderWithProviders(<GoogleCalendarCard />, { path });
}

describe("GoogleCalendarCard", () => {
  test("не подключён — вход у Google по ссылке трекера", async ({ api }) => {
    const assign = vi.fn();
    vi.stubGlobal("location", { ...window.location, assign });
    api.respond("POST /profile/google-calendar/login", { url: "https://accounts.google.test/auth" });
    const { user } = renderCard(api, null);

    await user.click(await screen.findByRole("button", { name: "Подключить" }));

    await vi.waitFor(() => expect(assign).toHaveBeenCalledWith("https://accounts.google.test/auth"));
  });

  test("выбор календарей сохраняется", async ({ api }) => {
    const { user } = renderCard(api, makeGoogleCalendarConnection());
    const save = await screen.findByRole("button", { name: "Сохранить выбор" });
    expect(save).toBeDisabled();

    await user.click(screen.getByRole("checkbox", { name: "Команда" }));
    await user.click(save);

    expect(api.mutations()).toEqual([
      {
        method: "PUT",
        path: "/profile/google-calendar/calendars",
        body: { calendar_ids: ["primary", "team@group.calendar.google.com"] },
      },
    ]);
  });

  test("нужен повторный вход — вместо выбора календарей кнопка входа", async ({ api }) => {
    renderCard(api, makeGoogleCalendarConnection({ status: "needs_reauth", last_error: "Доступ отозван" }));

    expect(await screen.findByRole("button", { name: "Войти снова" })).toBeInTheDocument();
    expect(screen.getByText("нужен повторный вход")).toBeInTheDocument();
    expect(screen.getByText("Доступ отозван")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Обновить сейчас" })).not.toBeInTheDocument();
  });

  test("обновить сейчас — синхронизация с числом событий", async ({ api, toasts }) => {
    api.respond("POST /profile/google-calendar/sync", { synced: true, events: 4 });
    const { user } = renderCard(api, makeGoogleCalendarConnection());

    await user.click(await screen.findByRole("button", { name: "Обновить сейчас" }));

    await vi.waitFor(() => expect(toasts.success).toHaveBeenCalledWith("Загружено событий: 4"));
  });

  test("Google отозвал доступ при загрузке календарей — карточка предлагает войти снова", async ({ api }) => {
    const connections = [
      makeGoogleCalendarConnection(),
      makeGoogleCalendarConnection({ status: "needs_reauth", last_error: "Доступ отозван" }),
    ];
    api.respond("GET /profile/google-calendar", () => connections.shift() ?? connections[0]);
    api.respond("GET /profile/google-calendar/calendars", { error: { status: 409, message: "Доступ отозван" } });
    renderWithProviders(<GoogleCalendarCard />, { path: "/profile" });

    expect(await screen.findByRole("button", { name: "Войти снова" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Сохранить выбор" })).not.toBeInTheDocument();
  });

  test("синхронизация не состоялась — ошибка вместо «Загружено событий»", async ({ api, toasts }) => {
    api.respond("POST /profile/google-calendar/sync", { synced: false, events: 0 });
    const { user } = renderCard(api, makeGoogleCalendarConnection());

    await user.click(await screen.findByRole("button", { name: "Обновить сейчас" }));

    await vi.waitFor(() => expect(toasts.error).toHaveBeenCalledWith("Календарь не обновлён"));
    expect(toasts.success).not.toHaveBeenCalled();
  });

  test.for([
    { result: "connected", kind: "success", text: "Google Calendar подключён" },
    { result: "error", kind: "error", text: "Не удалось подключить Google Calendar" },
  ] as const)("возврат из Google ?calendar=$result → тост", async ({ result, kind, text }, { api, toasts }) => {
    renderCard(api, null, `/profile?calendar=${result}`);

    await vi.waitFor(() => expect(toasts[kind]).toHaveBeenCalledWith(text));
    expect(toasts[kind]).toHaveBeenCalledTimes(1);
  });
});
