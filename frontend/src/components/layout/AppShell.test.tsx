import { screen } from "@testing-library/react";
import { describe, expect, vi } from "vitest";
import { AppShell } from "@/components/layout/AppShell";
import { ThemeProvider } from "@/stores/themeStore";
import { test } from "@/test/fixtures";
import { renderWithProviders } from "@/test/renderWithProviders";

vi.mock("@/lib/push", () => ({ ensurePushSubscription: vi.fn(() => Promise.resolve()) }));

describe("AppShell", () => {
  test.for([
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
});
