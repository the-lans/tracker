import { screen, within } from "@testing-library/react";
import { describe, expect, vi } from "vitest";
import { CreateTaskDialog } from "@/components/tasks/CreateTaskDialog";
import { UserRole, type JiraIssueDraft } from "@/lib/types";
import type { MockedApi } from "@/test/apiMock";
import { makeCurrentUser, makeLlmAccount, makeTask, makeUser } from "@/test/factories";
import { test } from "@/test/fixtures";
import { renderWithProviders } from "@/test/renderWithProviders";

const jiraDraft: JiraIssueDraft = {
  code: "RR-12370",
  title: "Фильтр по датам в отчётах",
  description: "Пользователи просят выбирать период отчёта.",
  issue_url: "https://example.atlassian.net/browse/RR-12370",
  attachments: [{ filename: "макет-фильтра.png", size: 204800 }],
};

/** Профиль с токеном Jira и сервер Jira — поле импорта доступно. */
function withJira(api: MockedApi) {
  api.respond("GET /profile", makeUser({ jira_token_set: true }));
  api.respond("GET /jira/server", { jira_url: "https://example.atlassian.net" });
}

function renderDialog(api: MockedApi, currentUser = makeCurrentUser()) {
  api.respond("POST /tasks", makeTask({ id: "t9" }));
  const onOpenChange = vi.fn();
  const view = renderWithProviders(<CreateTaskDialog open onOpenChange={onOpenChange} />, {
    currentUser,
  });
  return { ...view, onOpenChange, dialog: screen.getByRole("dialog") };
}

function createRequest(api: MockedApi) {
  return api.mutations().find((request) => request.path === "/tasks");
}

async function fillRequired(user: ReturnType<typeof renderDialog>["user"], code = "RR-12345") {
  await user.type(screen.getByLabelText("Код задачи"), code);
  await user.type(screen.getByLabelText("Название"), "Экспорт отчётов в CSV");
  await user.type(screen.getByLabelText("Описание"), "Кнопка выгрузки в CSV");
}

describe("CreateTaskDialog", () => {
  describe("создание", () => {
    test("необязательные поля уходят как null, задача без LLM-аккаунта допустима", async ({ api }) => {
      const { user, onOpenChange } = renderDialog(api);

      await fillRequired(user);
      await user.click(screen.getByRole("button", { name: "Создать" }));

      expect(createRequest(api)?.body).toEqual({
        code: "RR-12345",
        title: "Экспорт отчётов в CSV",
        description: "Кнопка выгрузки в CSV",
        guide_url: null,
        llm_account_id: null,
        repositories: [],
        parent_task_id: null,
        use_parent_summary: false,
        jira_issue_key: null,
      });
      await expect.poll(() => onOpenChange.mock.calls).toEqual([[false]]);
    });

    test.for(["RR 12345", " RR-12345"])("код «%s» с пробелом не отправляется", async (code, { api }) => {
      const { user } = renderDialog(api);

      await fillRequired(user, code);
      await user.click(screen.getByRole("button", { name: "Создать" }));

      expect(createRequest(api)).toBeUndefined();
      expect(screen.getByLabelText("Код задачи")).toBeInvalid();
    });

    test("выбранный репозиторий уходит с ролью и базовой веткой", async ({ api }) => {
      api.respond("GET /repositories", [
        { id: "r1", name: "web-app", git_url: "git@gitlab.example.com:shop/web-app.git", default_template_id: null },
      ]);
      const { user } = renderDialog(api);

      await fillRequired(user);
      await user.click(await screen.findByRole("checkbox", { name: "web-app" }));
      const branch = screen.getByLabelText("Базовая ветка");
      await user.clear(branch);
      await user.type(branch, "develop");
      await user.click(screen.getByRole("button", { name: "Создать" }));

      expect(createRequest(api)?.body).toMatchObject({
        repositories: [{ repository_id: "r1", role: "read_write", base_branch: "develop" }],
      });
    });

    test("ошибка сервера оставляет форму открытой с введёнными данными", async ({ api, toasts }) => {
      const { user, onOpenChange } = renderDialog(api);
      api.respond("POST /tasks", { error: { status: 409, message: "Задача с кодом RR-12345 уже есть" } });

      await fillRequired(user);
      await user.click(screen.getByRole("button", { name: "Создать" }));

      await expect.poll(() => toasts.error.mock.calls).toEqual([["Задача с кодом RR-12345 уже есть"]]);
      expect(onOpenChange).not.toHaveBeenCalled();
      expect(screen.getByLabelText("Код задачи")).toHaveValue("RR-12345");
    });
  });

  describe("LLM-аккаунт", () => {
    test.for([UserRole.USER, UserRole.ADMIN])(
      "%s выбирает только из своих аккаунтов",
      async (role, { api }) => {
        api.respond("GET /llm-accounts", [
          makeLlmAccount({ id: "acc1", label: "Мой Claude", created_by: "u1" }),
          makeLlmAccount({ id: "acc2", label: "Claude Олега", created_by: "u2" }),
        ]);
        const { user } = renderDialog(api, makeCurrentUser({ role }));

        await user.click(screen.getByRole("combobox", { name: "LLM-аккаунт" }));

        expect((await screen.findAllByRole("option")).map((option) => option.textContent)).toEqual([
          "Мой Claude",
        ]);
      },
    );

    test("без своих аккаунтов — подсказка, что доступны только скрипты", async ({ api }) => {
      api.respond("GET /llm-accounts", [makeLlmAccount({ created_by: "u2" })]);
      renderDialog(api);

      expect(await screen.findByText("LLM-аккаунтов пока нет")).toBeInTheDocument();
    });
  });

  describe("родительская задача", () => {
    test("саммари родителя нельзя включить без родителя", ({ api }) => {
      renderDialog(api);

      expect(
        screen.getByRole("checkbox", { name: "Передать саммари родителя первым сообщением сессии" }),
      ).toBeDisabled();
    });

    test("отказ от родителя сбрасывает передачу саммари", async ({ api }) => {
      api.respond("GET /tasks", [makeTask({ id: "t5", code: "RR-12300", title: "Каталог товаров" })]);
      const { user } = renderDialog(api);
      const summary = screen.getByRole("checkbox", {
        name: "Передать саммари родителя первым сообщением сессии",
      });

      await user.click(screen.getByRole("combobox", { name: "Родительская задача" }));
      await user.click(await screen.findByRole("option", { name: "RR-12300 · Каталог товаров" }));
      await user.click(summary);
      await user.click(screen.getByRole("combobox", { name: "Родительская задача" }));
      await user.click(await screen.findByRole("option", { name: "Без родителя" }));
      await fillRequired(user);
      await user.click(screen.getByRole("button", { name: "Создать" }));

      expect(summary).not.toBeChecked();
      expect(createRequest(api)?.body).toMatchObject({ parent_task_id: null, use_parent_summary: false });
    });
  });

  describe("импорт из Jira", () => {
    test("заполняет форму, а создание передаёт ключ для ссылки и вложений", async ({ api }) => {
      withJira(api);
      api.respond("GET /jira/issues/RR-12370", jiraDraft);
      const { user, dialog } = renderDialog(api);

      await user.type(await screen.findByLabelText("Ключ задачи Jira"), "RR-12370");
      await user.click(within(dialog).getByRole("button", { name: /Заполнить из Jira/ }));

      expect(await screen.findByDisplayValue("Фильтр по датам в отчётах")).toBeInTheDocument();
      expect(screen.getByLabelText("Код задачи")).toHaveValue("RR-12370");
      expect(screen.getByLabelText("Описание")).toHaveValue("Пользователи просят выбирать период отчёта.");

      await user.click(screen.getByRole("button", { name: "Создать" }));

      expect(createRequest(api)?.body).toMatchObject({ code: "RR-12370", jira_issue_key: "RR-12370" });
    });
  });
});
