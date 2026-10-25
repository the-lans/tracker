import { screen, within } from "@testing-library/react";
import { describe, expect } from "vitest";
import { JiraConnectionCard } from "@/components/profile/JiraConnectionCard";
import type { MockedApi } from "@/test/apiMock";
import { makeUser } from "@/test/factories";
import { test } from "@/test/fixtures";
import { renderWithProviders } from "@/test/renderWithProviders";

const JIRA_URL = "https://example.atlassian.net";

function renderCard(api: MockedApi, { jiraUrl = JIRA_URL as string | null, tokenSet = false, email = null as string | null } = {}) {
  const profile = makeUser({ jira_token_set: tokenSet, jira_email: email });
  api.respond("GET /jira/server", { jira_url: jiraUrl });
  api.respond("GET /profile", profile);
  api.respond("PUT /profile/jira", { ...profile, jira_token_set: true });
  api.respond("DELETE /profile/jira", { ...profile, jira_token_set: false, jira_email: null });
  return renderWithProviders(<JiraConnectionCard />);
}

const tokenField = () => screen.findByLabelText("Личный токен");
const saveButton = () => screen.getByRole("button", { name: "Сохранить" });

describe("JiraConnectionCard", () => {
  test("без адреса Jira подключать нечего", async ({ api }) => {
    renderCard(api, { jiraUrl: null });

    expect(await screen.findByText(/Адрес Jira ещё не задан/)).toBeInTheDocument();
    expect(screen.queryByLabelText("Личный токен")).not.toBeInTheDocument();
  });

  describe("первое подключение", () => {
    test("без токена форма не отправляется", async ({ api }) => {
      const { user } = renderCard(api);

      const field = await tokenField();

      await user.click(saveButton());

      expect(field).toBeInvalid();
      expect(api.mutations()).toEqual([]);
    });

    test("пустой email — Jira Server, токен уходит и стирается из поля", async ({ api, toasts }) => {
      const { user } = renderCard(api);

      await user.type(await tokenField(), "pat-test-123");
      await user.click(saveButton());

      expect(api.mutations()).toEqual([
        { method: "PUT", path: "/profile/jira", body: { jira_email: null, jira_token: "pat-test-123" } },
      ]);
      await expect.poll(() => toasts.success.mock.calls).toEqual([["Подключение к Jira сохранено"]]);
      expect(await tokenField()).toHaveValue("");
    });
  });

  describe("токен уже сохранён", () => {
    test("токен не показывается, пустое поле его не стирает", async ({ api }) => {
      const { user } = renderCard(api, { tokenSet: true, email: "anna@example.com" });
      const field = await tokenField();

      expect(field).toHaveValue("");
      expect(field).toHaveAttribute("type", "password");
      expect(field).toHaveAttribute("placeholder", "Сохранён — введите новый, чтобы заменить");
      await user.click(saveButton());

      expect(api.mutations()).toEqual([
        { method: "PUT", path: "/profile/jira", body: { jira_email: "anna@example.com", jira_token: null } },
      ]);
    });

    test.for([
      { failing: false, route: null },
      { failing: true, route: "DELETE /profile/jira" },
    ])("отключение после подтверждения, ошибка: $failing", async ({ failing, route }, { api, toasts }) => {
      const { user } = renderCard(api, { tokenSet: true });
      if (route) api.respond(route, { error: { status: 500, message: "Сервис недоступен" } });

      await user.click(await screen.findByRole("button", { name: `Удалить ${JIRA_URL}` }));
      await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Удалить" }));

      expect(api.mutations()).toEqual([{ method: "DELETE", path: "/profile/jira", body: undefined }]);
      await expect.poll(() => toasts.error.mock.calls).toEqual(failing ? [["Сервис недоступен"]] : []);
    });
  });
});
