import { screen } from "@testing-library/react";
import { describe, expect, vi } from "vitest";
import { McpServerForm } from "@/components/admin/McpServerForm";
import { McpAuthType, McpIsolationMode, type McpServer } from "@/lib/types";
import { test } from "@/test/fixtures";
import { renderWithProviders } from "@/test/renderWithProviders";

const PATH_TEMPLATE = "{{task.repos_path}}/.mcp-profiles/playwright";

const playwright: McpServer = {
  id: "m1",
  name: "playwright",
  url: "http://playwright-mcp.example.com/mcp",
  auth_type: McpAuthType.API_KEY,
  is_healthy: true,
  has_stateful_resource: true,
  isolation_mode: McpIsolationMode.PER_TASK_DATA_DIR,
  isolation_path_template: PATH_TEMPLATE,
};

function renderForm(server?: McpServer) {
  const onSaved = vi.fn();
  return { ...renderWithProviders(<McpServerForm server={server} onSaved={onSaved} onCancel={() => {}} />), onSaved };
}

type User = ReturnType<typeof renderForm>["user"];

async function fillNew(user: User) {
  await user.type(screen.getByLabelText("Название"), "playwright");
  await user.type(screen.getByLabelText("URL"), "http://playwright-mcp.example.com/mcp");
}

async function chooseIsolation(user: User, label: string) {
  await user.click(screen.getByRole("combobox", { name: "Режим изоляции" }));
  await user.click(await screen.findByRole("option", { name: label }));
}

const save = () => screen.getByRole("button", { name: "Сохранить" });

describe("McpServerForm", () => {
  describe("изоляция сервера с состоянием (правило 3)", () => {
    test("без режима изоляции сохранить нельзя", async () => {
      const { user } = renderForm();

      await fillNew(user);
      await user.click(screen.getByRole("switch", { name: "Ресурс с состоянием" }));

      expect(screen.getByText("Выберите режим изоляции")).toBeInTheDocument();
      expect(save()).toBeDisabled();
    });

    test.for([
      { path: "", valid: false },
      { path: "/data/profiles/playwright", valid: false },
      { path: PATH_TEMPLATE, valid: true },
    ])("своя папка, путь «$path» → можно сохранить: $valid", async ({ path, valid }) => {
      const { user } = renderForm();

      await fillNew(user);
      await user.click(screen.getByRole("switch", { name: "Ресурс с состоянием" }));
      await chooseIsolation(user, "своя папка у задачи");
      if (path) await user.type(screen.getByLabelText("Шаблон пути профиля"), path.replace(/\{/g, "{{"));

      expect(save()).toHaveProperty("disabled", !valid);
    });

    test("изолированный режим уходит без шаблона пути", async ({ api }) => {
      const { user } = renderForm(playwright);

      await chooseIsolation(user, "изолированный режим");
      await user.click(save());

      expect(api.mutations()).toEqual([
        {
          method: "PATCH",
          path: "/mcp-servers/m1",
          body: expect.objectContaining({
            isolation_mode: McpIsolationMode.ISOLATED_FLAG,
            isolation_path_template: null,
          }),
        },
      ]);
    });

    test("сервер без состояния уходит без изоляции", async ({ api }) => {
      const { user } = renderForm(playwright);

      await user.click(screen.getByRole("switch", { name: "Ресурс с состоянием" }));
      await user.click(save());

      expect(api.mutations()[0].body).toMatchObject({
        has_stateful_resource: false,
        isolation_mode: null,
        isolation_path_template: null,
      });
    });
  });

  describe("секрет авторизации", () => {
    test("новый сервер без авторизации — пустой секрет", async ({ api }) => {
      const { user } = renderForm();

      await fillNew(user);
      await user.click(save());

      expect(screen.queryByLabelText("Ключ/токен")).not.toBeInTheDocument();
      expect(api.mutations()[0]).toMatchObject({
        method: "POST",
        path: "/mcp-servers",
        body: { auth_type: McpAuthType.NONE, auth_config: "" },
      });
    });

    test.for([
      { typed: "", sent: false },
      { typed: "sk-test-new", sent: true },
    ])("правка: введённый ключ «$typed» уходит: $sent", async ({ typed, sent }, { api }) => {
      const { user } = renderForm(playwright);
      const field = screen.getByLabelText("Новое значение (оставьте пустым, чтобы не менять)");

      expect(field).toHaveAttribute("type", "password");
      expect(field).toHaveValue("");
      if (typed) await user.type(field, typed);
      await user.click(save());

      const body = api.mutations()[0].body;
      if (sent) expect(body).toHaveProperty("auth_config", typed);
      else expect(body).not.toHaveProperty("auth_config");
    });
  });

  test("ошибка сервера показывается уведомлением", async ({ api, toasts }) => {
    api.respond("PATCH /mcp-servers/m1", { error: { status: 422, message: "URL недоступен" } });
    const { user, onSaved } = renderForm(playwright);

    await user.click(save());

    await expect.poll(() => toasts.error.mock.calls).toEqual([["URL недоступен"]]);
    expect(onSaved).not.toHaveBeenCalled();
  });
});
