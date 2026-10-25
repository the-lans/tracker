import { screen } from "@testing-library/react";
import { describe, expect, vi } from "vitest";
import { JiraImportField } from "@/components/tasks/JiraImportField";
import type { JiraIssueDraft } from "@/lib/types";
import type { MockedApi } from "@/test/apiMock";
import { makeUser } from "@/test/factories";
import { test } from "@/test/fixtures";
import { renderWithProviders } from "@/test/renderWithProviders";

const JIRA_URL = "https://example.atlassian.net";

const draft: JiraIssueDraft = {
  code: "RR-12370",
  title: "Фильтр по датам в отчётах",
  description: "Период отчёта.",
  issue_url: `${JIRA_URL}/browse/RR-12370`,
  attachments: [
    { filename: "макет-фильтра.png", size: 204800 },
    { filename: "требования.pdf", size: 1572864 },
  ],
};

function renderField(api: MockedApi, { jiraUrl = JIRA_URL as string | null, tokenSet = true } = {}) {
  api.respond("GET /jira/server", { jira_url: jiraUrl });
  api.respond("GET /profile", makeUser({ jira_token_set: tokenSet }));
  const onImported = vi.fn();
  return { ...renderWithProviders(<JiraImportField onImported={onImported} />), onImported };
}

const fillButton = () => screen.getByRole("button", { name: /Заполнить из Jira/ });

describe("JiraImportField", () => {
  describe("доступность", () => {
    test("без адреса Jira у администратора импорт недоступен", async ({ api }) => {
      renderField(api, { jiraUrl: null });

      expect(
        await screen.findByText("Заполнение из Jira недоступно: администратор не указал адрес Jira."),
      ).toBeInTheDocument();
      expect(screen.queryByLabelText("Ключ задачи Jira")).not.toBeInTheDocument();
    });

    test("без личного токена — ссылка на профиль", async ({ api }) => {
      renderField(api, { tokenSet: false });

      expect(await screen.findByRole("link", { name: "профиле" })).toHaveAttribute("href", "/profile");
      expect(screen.queryByLabelText("Ключ задачи Jira")).not.toBeInTheDocument();
    });

    test.for(["", "   "])("ключ «%s» — кнопка неактивна", async (key, { api }) => {
      const { user } = renderField(api);
      const field = await screen.findByLabelText("Ключ задачи Jira");

      if (key) await user.type(field, key);

      expect(fillButton()).toBeDisabled();
    });
  });

  describe("запрос задачи", () => {
    test.for([
      { key: "  RR-12370 ", path: "/jira/issues/RR-12370" },
      { key: "RR/12370", path: "/jira/issues/RR%2F12370" },
    ])("ключ «$key» → $path", async ({ key, path }, { api }) => {
      api.respond(`GET ${path}`, draft);
      const { user, onImported } = renderField(api);

      await user.type(await screen.findByLabelText("Ключ задачи Jira"), key);
      await user.click(fillButton());

      await expect.poll(() => onImported.mock.calls).toEqual([[draft]]);
      expect(api.requests.map((request) => request.path)).toContain(path);
    });

    test("после импорта видна ссылка на задачу и вложения с размером", async ({ api }) => {
      api.respond("GET /jira/issues/RR-12370", draft);
      const { user } = renderField(api);

      await user.type(await screen.findByLabelText("Ключ задачи Jira"), "RR-12370");
      await user.click(fillButton());

      expect(await screen.findByRole("link", { name: "RR-12370" })).toHaveAttribute("href", draft.issue_url);
      expect(
        screen.getByText(/вложения скопируются в артефакты: макет-фильтра\.png \(200 КБ\), требования\.pdf \(1,5 МБ\)/),
      ).toBeInTheDocument();
    });

    test("ошибка Jira показывается уведомлением, форма не заполняется", async ({ api, toasts }) => {
      api.respond("GET /jira/issues/RR-404", { error: { status: 404, message: "Задача RR-404 не найдена в Jira" } });
      const { user, onImported } = renderField(api);

      await user.type(await screen.findByLabelText("Ключ задачи Jira"), "RR-404");
      await user.click(fillButton());

      await expect.poll(() => toasts.error.mock.calls).toEqual([["Задача RR-404 не найдена в Jira"]]);
      expect(onImported).not.toHaveBeenCalled();
    });
  });
});
