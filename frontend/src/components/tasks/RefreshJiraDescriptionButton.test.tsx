import { screen } from "@testing-library/react";
import { describe, expect } from "vitest";
import { RefreshJiraDescriptionButton } from "@/components/tasks/RefreshJiraDescriptionButton";
import { test } from "@/test/fixtures";
import { renderWithProviders } from "@/test/renderWithProviders";

describe("RefreshJiraDescriptionButton", () => {
  test("запрашивает описание из Jira и сообщает об успехе", async ({
    api,
    toasts,
  }) => {
    const { user } = renderWithProviders(
      <RefreshJiraDescriptionButton taskId="t1" />,
    );

    await user.click(screen.getByRole("button", { name: /Обновить из Jira/ }));

    await expect
      .poll(() => toasts.success)
      .toHaveBeenCalledWith("Описание обновлено из Jira");
    expect(api.mutations().map((request) => request.path)).toEqual([
      "/jira/tasks/t1/description",
    ]);
  });

  test("показывает причину отказа Jira", async ({ api, toasts }) => {
    api.respond("POST /jira/tasks/t1/description", {
      error: {
        status: 409,
        message: "Описание задачи отличается от описания в Jira",
      },
    });
    const { user } = renderWithProviders(
      <RefreshJiraDescriptionButton taskId="t1" />,
    );

    await user.click(screen.getByRole("button", { name: /Обновить из Jira/ }));

    await expect
      .poll(() => toasts.error)
      .toHaveBeenCalledWith("Описание задачи отличается от описания в Jira");
  });
});
