import { screen } from "@testing-library/react";
import { describe, expect, vi } from "vitest";
import { LogoutActions } from "@/components/profile/LogoutActions";
import { test } from "@/test/fixtures";
import { renderWithProviders } from "@/test/renderWithProviders";

describe("LogoutActions", () => {
  test("«Выйти» — только локально, без запроса", async ({ api }) => {
    const logout = vi.fn();
    const { user } = renderWithProviders(<LogoutActions />, { logout });

    await user.click(screen.getByRole("button", { name: "Выйти" }));

    expect(logout).toHaveBeenCalledOnce();
    expect(api.mutations()).toEqual([]);
  });

  test.for([
    { outcome: "успех", response: null, loggedOut: true },
    { outcome: "ошибка", response: { error: { status: 500, message: "Сбой" } }, loggedOut: false },
  ])("выйти на всех устройствах: $outcome", async ({ response, loggedOut }, { api, toasts }) => {
    api.respond("POST /auth/logout-all", response);
    const logout = vi.fn();
    const { user } = renderWithProviders(<LogoutActions />, { logout });

    await user.click(screen.getByRole("button", { name: "Выйти на всех устройствах" }));
    await user.click(await screen.findByRole("button", { name: "Выйти везде" }));

    expect(api.mutations()).toEqual([{ method: "POST", path: "/auth/logout-all", body: undefined }]);
    await expect.poll(() => logout.mock.calls.length + toasts.error.mock.calls.length).toBe(1);
    expect(logout.mock.calls.length).toBe(Number(loggedOut));
  });
});
