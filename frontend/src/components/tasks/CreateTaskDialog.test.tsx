import { screen, within } from "@testing-library/react";
import { describe, expect, vi } from "vitest";
import { CreateTaskDialog } from "@/components/tasks/CreateTaskDialog";
import { LlmAccountStatus, UserRole, type JiraIssueDraft } from "@/lib/types";
import type { MockedApi } from "@/test/apiMock";
import { makeCurrentUser, makeLlmAccount, makeRepository, makeTask, makeUser } from "@/test/factories";
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
  test.for([
    { field: "Код задачи", required: true },
    { field: "Название", required: true },
    { field: "Описание", required: true },
    { field: "Гайд (URL Confluence)", required: false },
    { field: "Стартовый LLM-аккаунт", required: false },
  ])("«$field» — обязательное: $required", ({ field, required }, { api }) => {
    renderDialog(api);

    const label = screen.getByText(field, { selector: "label" });
    expect(label.hasAttribute("data-required")).toBe(required);
  });

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
      const field = screen.getByLabelText("Код задачи");
      expect(field).toBeInvalid();
      expect(field).toHaveAttribute("aria-invalid", "true");
      expect(field).toHaveAccessibleDescription(/не должен содержать пробелов/);
    });

    test("код без пробелов не помечен ошибкой", async ({ api }) => {
      const { user } = renderDialog(api);

      await fillRequired(user, "RR-12345");

      expect(screen.getByLabelText("Код задачи")).toHaveAttribute("aria-invalid", "false");
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    });

    test("базовая ветка по умолчанию — из настроек репозитория", async ({ api }) => {
      api.respond("GET /repositories", [makeRepository({ default_branch: "develop" })]);
      const { user } = renderDialog(api);

      await fillRequired(user);
      await user.click(await screen.findByRole("checkbox", { name: "web-app" }));

      expect(screen.getByLabelText("Базовая ветка")).toHaveValue("develop");
      await user.click(screen.getByRole("button", { name: "Создать" }));
      expect(createRequest(api)?.body).toMatchObject({
        repositories: [{ repository_id: "r1", role: "read_write", base_branch: "develop" }],
      });
    });

    test("выбранный репозиторий уходит с ролью и базовой веткой", async ({ api }) => {
      api.respond("GET /repositories", [makeRepository()]);
      const { user } = renderDialog(api);

      await fillRequired(user);
      await user.click(await screen.findByRole("checkbox", { name: "web-app" }));
      const branch = screen.getByLabelText("Базовая ветка");
      await user.clear(branch);
      await user.type(branch, "release/1.2");
      await user.click(screen.getByRole("button", { name: "Создать" }));

      expect(createRequest(api)?.body).toMatchObject({
        repositories: [{ repository_id: "r1", role: "read_write", base_branch: "release/1.2" }],
      });
    });

    test("ошибка сервера оставляет форму открытой с введёнными данными", async ({ api, toasts }) => {
      const { user, onOpenChange } = renderDialog(api);
      api.respond("POST /tasks", { error: { status: 409, message: "Пайплайн в архиве" } });

      await fillRequired(user);
      await user.click(screen.getByRole("button", { name: "Создать" }));

      await expect.poll(() => toasts.error.mock.calls).toEqual([["Пайплайн в архиве"]]);
      expect(onOpenChange).not.toHaveBeenCalled();
      expect(screen.getByLabelText("Код задачи")).toHaveValue("RR-12345");
      expect(screen.getByLabelText("Код задачи")).not.toHaveAttribute("aria-invalid", "true");
    });

    test.for([
      { code: "task_code_taken", status: 409, message: "Задача с кодом RR-12345 уже существует" },
      { code: "invalid_task_code", status: 422, message: "Код задачи не может содержать «..» и «@{»" },
    ])("ошибка «$code» — под полем кода, без уведомления", async (error, { api, toasts }) => {
      const { user, onOpenChange } = renderDialog(api);
      api.respond("POST /tasks", { error });

      await fillRequired(user);
      await user.click(screen.getByRole("button", { name: "Создать" }));

      const field = screen.getByLabelText("Код задачи");
      await vi.waitFor(() => expect(field).toHaveAccessibleDescription(new RegExp(error.message)));
      expect(field).toHaveAttribute("aria-invalid", "true");
      expect(toasts.error).not.toHaveBeenCalled();
      expect(onOpenChange).not.toHaveBeenCalled();

      await user.type(field, "-2");

      expect(field).not.toHaveAttribute("aria-invalid", "true");
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
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

        await user.click(screen.getByRole("combobox", { name: "Стартовый LLM-аккаунт" }));

        expect((await screen.findAllByRole("option")).map((option) => option.textContent)).toEqual([
          "Автоматически",
          "Мой Claude",
        ]);
      },
    );

    test("стартовый — только из активных, в порядке переключения", async ({ api }) => {
      api.respond("GET /llm-accounts", [
        makeLlmAccount({ id: "a1", label: "Claude — основной" }),
        makeLlmAccount({ id: "a2", label: "Codex — нужен вход", status: LlmAccountStatus.LOGIN_REQUIRED }),
        makeLlmAccount({ id: "a3", label: "Claude — выключен", status: LlmAccountStatus.DISABLED }),
        makeLlmAccount({ id: "a4", label: "Claude — запасной" }),
      ]);
      const { user } = renderDialog(api);

      await user.click(screen.getByRole("combobox", { name: "Стартовый LLM-аккаунт" }));

      expect((await screen.findAllByRole("option")).map((option) => option.textContent)).toEqual([
        "Автоматически",
        "Claude — основной",
        "Claude — запасной",
      ]);
    });

    test("по умолчанию «Автоматически», выбор аккаунта и возврат к автоматическому", async ({ api }) => {
      api.respond("GET /llm-accounts", [makeLlmAccount({ id: "a1", label: "Claude — основной" })]);
      const { user } = renderDialog(api);
      const field = screen.getByRole("combobox", { name: "Стартовый LLM-аккаунт" });

      await vi.waitFor(() => expect(field).toHaveTextContent("Автоматически"));
      await user.click(field);
      await user.click(await screen.findByRole("option", { name: "Claude — основной" }));
      await user.click(field);
      await user.click(await screen.findByRole("option", { name: "Автоматически" }));
      await fillRequired(user);
      await user.click(screen.getByRole("button", { name: "Создать" }));

      expect(createRequest(api)?.body).toMatchObject({ llm_account_id: null });
    });

    test("нет активных аккаунтов — подсказка войти или включить", async ({ api }) => {
      api.respond("GET /llm-accounts", [makeLlmAccount({ status: LlmAccountStatus.LOGIN_REQUIRED })]);
      renderDialog(api);

      expect(await screen.findByText(/Нет активных аккаунтов/)).toBeInTheDocument();
    });

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

    test("родителя находит поиск по коду или названию", async ({ api }) => {
      api.respond("GET /tasks", [
        makeTask({ id: "t5", code: "RR-12300", title: "Каталог товаров" }),
        makeTask({ id: "t6", code: "RR-12301", title: "Корзина" }),
      ]);
      const { user } = renderDialog(api);

      await user.type(screen.getByRole("combobox", { name: "Родительская задача" }), "корз");
      await user.click(await screen.findByRole("option", { name: "RR-12301 · Корзина" }));
      await fillRequired(user);
      await user.click(screen.getByRole("button", { name: "Создать" }));

      expect(createRequest(api)?.body).toMatchObject({ parent_task_id: "t6" });
    });

    test("Escape в поиске родителя закрывает список, а не диалог", async ({ api }) => {
      api.respond("GET /tasks", [makeTask({ id: "t5", code: "RR-12300", title: "Каталог товаров" })]);
      const { user, onOpenChange } = renderDialog(api);

      await user.type(screen.getByRole("combobox", { name: "Родительская задача" }), "кат");
      await user.keyboard("{Escape}");

      expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
      expect(onOpenChange).not.toHaveBeenCalled();
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
