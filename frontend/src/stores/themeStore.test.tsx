import type { ReactNode } from "react";
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useTheme } from "@/hooks/useTheme";
import { ThemeProvider } from "@/stores/themeStore";

const STORAGE_KEY = "tracker.theme";

function stubSystemTheme(dark: boolean) {
  vi.stubGlobal(
    "matchMedia",
    vi.fn((query: string) => ({ matches: dark && query === "(prefers-color-scheme: dark)" })),
  );
}

function renderTheme() {
  return renderHook(() => useTheme(), {
    wrapper: ({ children }: { children: ReactNode }) => <ThemeProvider>{children}</ThemeProvider>,
  });
}

const appliedTheme = () => document.documentElement.getAttribute("data-theme");

describe("ThemeProvider", () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => {
    vi.restoreAllMocks();
    document.documentElement.removeAttribute("data-theme");
  });

  it.each([
    { stored: "dark", system: false, theme: "dark" },
    { stored: "light", system: true, theme: "light" },
    { stored: null, system: true, theme: "dark" },
    { stored: null, system: false, theme: "light" },
    { stored: "purple", system: true, theme: "dark" },
  ])("сохранено $stored, системная тёмная: $system → $theme", ({ stored, system, theme }) => {
    if (stored) localStorage.setItem(STORAGE_KEY, stored);
    stubSystemTheme(system);

    const { result } = renderTheme();

    expect(result.current.theme).toBe(theme);
    expect(appliedTheme()).toBe(theme);
  });

  it("переключение применяется и запоминается", () => {
    stubSystemTheme(false);
    const { result } = renderTheme();

    act(() => result.current.toggleTheme());

    expect(appliedTheme()).toBe("dark");
    expect(localStorage.getItem(STORAGE_KEY)).toBe("dark");
    act(() => result.current.setTheme("light"));
    expect(localStorage.getItem(STORAGE_KEY)).toBe("light");
  });

  it("без доступа к localStorage тема берётся из системы и переключается", () => {
    stubSystemTheme(true);
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new DOMException("denied", "SecurityError");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("denied", "SecurityError");
    });

    const { result } = renderTheme();
    expect(result.current.theme).toBe("dark");
    act(() => result.current.toggleTheme());

    expect(appliedTheme()).toBe("light");
  });

  it("вне ThemeProvider — понятная ошибка", () => {
    vi.spyOn(console, "error").mockImplementation(() => {});

    expect(() => renderHook(() => useTheme())).toThrow("useTheme должен использоваться внутри ThemeProvider");
  });
});
