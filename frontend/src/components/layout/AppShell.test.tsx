import { screen } from "@testing-library/react";
import { describe, expect, vi } from "vitest";
import { AppShell } from "@/components/layout/AppShell";
import { ThemeProvider } from "@/stores/themeStore";
import { test } from "@/test/fixtures";
import { renderWithProviders } from "@/test/renderWithProviders";

vi.mock("@/lib/push", () => ({ ensurePushSubscription: vi.fn(() => Promise.resolve()) }));

describe("AppShell", () => {
  test.for([
    { path: "/daily", title: "Дейли" },
    { path: "/archive", title: "Архив" },
    { path: "/events", title: "События" },
    { path: "/categories", title: "Категории" },
    { path: "/admin/monitoring", title: "Мониторинг" },
    { path: "/tasks/t1", title: "Tracker" },
  ])("заголовок шапки на $path — «$title»", ({ path, title }) => {
    renderWithProviders(
      <ThemeProvider>
        <AppShell />
      </ThemeProvider>,
      { path },
    );

    expect(screen.getByRole("heading", { level: 1, name: title })).toBeInTheDocument();
  });

  describe("счётчик ожидающих решения на кнопке меню", () => {
    function renderShell() {
      return renderWithProviders(
        <ThemeProvider>
          <AppShell />
        </ThemeProvider>,
      );
    }

    test("показывает число и попадает в имя кнопки", async ({ api }) => {
      api.respond("GET /tasks/awaiting-count", { count: 3 });
      renderShell();

      const button = await screen.findByRole("button", { name: "Меню, ожидают решения: 3" });

      expect(button).toHaveTextContent("3");
    });

    test("больше 99 — «99+», а в имени кнопки точное число", async ({ api }) => {
      api.respond("GET /tasks/awaiting-count", { count: 128 });
      renderShell();

      const button = await screen.findByRole("button", { name: "Меню, ожидают решения: 128" });

      expect(button).toHaveTextContent("99+");
      expect(button).not.toHaveTextContent("128");
    });

    test("нет ожидающих — кнопка без счётчика", async ({ api }) => {
      api.respond("GET /tasks/awaiting-count", { count: 0 });
      renderShell();

      const button = await screen.findByRole("button", { name: "Меню" });

      expect(button).not.toHaveTextContent(/\d/);
    });
  });
});
