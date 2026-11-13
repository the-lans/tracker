import { screen } from "@testing-library/react";
import { describe, expect } from "vitest";
import { Sidebar } from "@/components/layout/Sidebar";
import { UserRole } from "@/lib/types";
import { ThemeProvider } from "@/stores/themeStore";
import { makeCurrentUser } from "@/test/factories";
import { test } from "@/test/fixtures";
import { renderWithProviders } from "@/test/renderWithProviders";

function renderSidebar(role: UserRole, path = "/") {
  return renderWithProviders(
    <ThemeProvider>
      <Sidebar />
    </ThemeProvider>,
    { currentUser: makeCurrentUser({ role }), path },
  );
}

describe("Sidebar", () => {
  test.for([
    { role: UserRole.USER, admin: false },
    { role: UserRole.ADMIN, admin: true },
  ])("$role: «События» есть, «Мониторинг» — $admin", ({ role, admin }) => {
    renderSidebar(role);

    expect(screen.getByRole("link", { name: "События" })).toHaveAttribute("href", "/events");
    expect(screen.queryByRole("link", { name: "Мониторинг" }) !== null).toBe(admin);
    expect(screen.queryByRole("link", { name: "Администрирование" }) !== null).toBe(admin);
  });

  test("«Категории» — перед «Шаблонами»", () => {
    renderSidebar(UserRole.USER);

    const names = screen.getAllByRole("link").map((link) => link.textContent);
    expect(screen.getByRole("link", { name: "Категории" })).toHaveAttribute("href", "/categories");
    expect(names.indexOf("Категории") + 1).toBe(names.indexOf("Шаблоны"));
  });

  test("«Мониторинг» ведёт на отдельную страницу администрирования", () => {
    renderSidebar(UserRole.ADMIN);

    expect(screen.getByRole("link", { name: "Мониторинг" })).toHaveAttribute("href", "/admin/monitoring");
  });

  test.for([
    { path: "/admin", current: "Администрирование" },
    { path: "/admin/monitoring", current: "Мониторинг" },
  ])("$path → выделен только «$current»", ({ path, current }) => {
    renderSidebar(UserRole.ADMIN, path);

    const highlighted = screen
      .getAllByRole("link")
      .filter((link) => link.getAttribute("aria-current") === "page")
      .map((link) => link.textContent);
    expect(highlighted).toEqual([current]);
  });
});
