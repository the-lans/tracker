import type { ComponentProps } from "react";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect } from "vitest";
import { Sidebar } from "@/components/layout/Sidebar";
import { UserRole } from "@/lib/types";
import { ThemeProvider } from "@/stores/themeStore";
import { makeCurrentUser } from "@/test/factories";
import { test } from "@/test/fixtures";
import { renderWithProviders } from "@/test/renderWithProviders";

function renderSidebar(role: UserRole, path = "/", props: ComponentProps<typeof Sidebar> = {}) {
  return renderWithProviders(
    <ThemeProvider>
      <Sidebar {...props} />
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

  test("Дашборд → Дейли → Категории → Пайплайны", () => {
    renderSidebar(UserRole.USER);

    const names = screen.getAllByRole("link").map((link) => link.textContent);
    const start = names.indexOf("Дашборд");
    expect(screen.getByRole("link", { name: "Дейли" })).toHaveAttribute("href", "/daily");
    expect(screen.getByRole("link", { name: "Категории" })).toHaveAttribute("href", "/categories");
    expect(names.slice(start, start + 4)).toEqual(["Дашборд", "Дейли", "Категории", "Пайплайны"]);
  });

  test("«Архив» — сразу после «События»", () => {
    renderSidebar(UserRole.USER);

    const names = screen.getAllByRole("link").map((link) => link.textContent);
    expect(screen.getByRole("link", { name: "Архив" })).toHaveAttribute("href", "/archive");
    expect(names.indexOf("События") + 1).toBe(names.indexOf("Архив"));
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

  describe("режим значков", () => {
    test("подписей нет, но ссылки сохраняют имена и подсказки", () => {
      renderSidebar(UserRole.ADMIN, "/", { compact: true, width: 72 });

      const events = screen.getByRole("link", { name: "События" });
      expect(events).toHaveAttribute("title", "События");
      expect(events.textContent).toBe("");
      expect(screen.queryByText("Tracker")).not.toBeInTheDocument();
      // Заголовок раздела остаётся только для скринридеров.
      expect(screen.getByText("Настройки")).toHaveClass("sr-only");
      expect(screen.getByRole("link", { name: /^Профиль:/ })).toHaveAttribute("href", "/profile");
    });

    test("тема переключается одной кнопкой", async () => {
      const user = userEvent.setup();
      renderSidebar(UserRole.USER, "/", { compact: true, width: 72 });

      const toggle = screen.getByRole("button", { name: /Включить (тёмную|светлую) тему/ });
      const before = toggle.getAttribute("aria-label");
      await user.click(toggle);
      expect(screen.getByRole("button", { name: /Включить (тёмную|светлую) тему/ }).getAttribute("aria-label")).not.toBe(before);
    });

    test("ширина задаётся стилем", () => {
      renderSidebar(UserRole.USER, "/", { width: 320 });
      expect(screen.getByRole("complementary", { name: "Основное меню" })).toHaveStyle({ width: "320px" });
    });
  });

  test("у каждого пункта меню свой значок", () => {
    renderSidebar(UserRole.ADMIN);

    const icons = screen
      .getAllByRole("link")
      .map((link) => link.querySelector("svg")?.getAttribute("class") ?? "")
      .filter((cls) => cls.includes("lucide-"))
      .map((cls) => cls.split(" ").find((c) => c.startsWith("lucide-") && c !== "lucide")!);
    expect(new Set(icons).size).toBe(icons.length);
  });
});
