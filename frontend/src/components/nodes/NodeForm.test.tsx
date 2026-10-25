import { screen } from "@testing-library/react";
import { describe, expect, vi } from "vitest";
import { NodeForm } from "@/components/nodes/NodeForm";
import { NodeType, ScriptLanguage, type NodeItem } from "@/lib/types";
import type { MockedApi } from "@/test/apiMock";
import { makeNode } from "@/test/factories";
import { test } from "@/test/fixtures";
import { renderWithProviders } from "@/test/renderWithProviders";

type Mode = "pipeline" | "library";

function renderForm(api: MockedApi, { mode = "pipeline" as Mode, node }: { mode?: Mode; node?: NodeItem } = {}) {
  api.respond("GET /system-settings", {
    default_timeout_seconds: 600,
    default_max_retries: 3,
    default_retry_base_delay_seconds: 5,
  });
  const onSaved = vi.fn();
  const view = renderWithProviders(
    <NodeForm mode={mode} pipelineId={mode === "pipeline" ? "p1" : undefined} orderIndex={2} node={node} onSaved={onSaved} onCancel={() => {}} />,
  );
  return { ...view, onSaved };
}

async function chooseType(user: ReturnType<typeof renderForm>["user"], label: string) {
  await user.click(screen.getByRole("combobox", { name: "Тип ноды" }));
  await user.click(await screen.findByRole("option", { name: label }));
}

const savedBody = (api: MockedApi) => api.mutations().at(-1)?.body;
const save = () => screen.getByRole("button", { name: "Сохранить" });

describe("NodeForm", () => {
  describe("поля по типу ноды", () => {
    test.for([
      { type: NodeType.PLAIN_PROMPT, label: "Обычный промт", field: "Текст промта" },
      { type: NodeType.PLAN_PROMPT, label: "Режим планирования", field: "Текст промта" },
      { type: NodeType.SLASH_COMMAND, label: "Слэш-команда", field: "Слэш-команда" },
      { type: NodeType.SCRIPT, label: "Скрипт", field: "Содержимое скрипта" },
    ])("$type → поле «$field», чужих полей нет", async ({ label, field }, { api }) => {
      const { user } = renderForm(api);

      await chooseType(user, label);

      const all = ["Текст промта", "Слэш-команда", "Содержимое скрипта"];
      for (const name of all) {
        expect(screen.queryByLabelText(name) !== null).toBe(name === field);
      }
    });

    test("в библиотеке нет режима планирования и очистки контекста", async ({ api }) => {
      const { user } = renderForm(api, { mode: "library" });

      await user.click(screen.getByRole("combobox", { name: "Тип ноды" }));

      expect((await screen.findAllByRole("option")).map((option) => option.textContent)).toEqual([
        "Обычный промт",
        "Слэш-команда",
        "Скрипт",
      ]);
    });

    test.for([
      { mode: "pipeline" as Mode, nodeVariables: true },
      { mode: "library" as Mode, nodeVariables: false },
    ])("$mode: подсказка {{node.*}} — $nodeVariables", ({ mode, nodeVariables }, { api }) => {
      renderForm(api, { mode });

      expect(screen.queryByText(/\{\{node\.\*\}\}/) !== null).toBe(nodeVariables);
    });

    test("слэш-команда — без подсказки переменных, передаётся буквально", async ({ api }) => {
      const { user } = renderForm(api);

      await chooseType(user, "Слэш-команда");

      expect(screen.queryByText(/Доступные переменные/)).not.toBeInTheDocument();
      expect(screen.getByText(/шаблонизатор не применяется/)).toBeInTheDocument();
    });
  });

  describe("сохранение", () => {
    test("уходят только поля выбранного типа, остальное — null", async ({ api }) => {
      const { user, onSaved } = renderForm(api);

      await user.type(screen.getByLabelText("Название"), "Тесты и линтеры");
      await user.type(screen.getByLabelText("Текст промта"), "Черновик");
      await chooseType(user, "Скрипт");
      await user.type(screen.getByLabelText("Содержимое скрипта"), "pytest -q");
      await user.click(save());

      expect(api.mutations()).toHaveLength(1);
      expect(savedBody(api)).toEqual({
        pipeline_id: "p1",
        order_index: 2,
        name: "Тесты и линтеры",
        description: null,
        node_type: NodeType.SCRIPT,
        prompt_template: null,
        command_invocation: null,
        script_language: ScriptLanguage.PYTHON,
        script_content: "pytest -q",
        guide_url: null,
        is_skipped: false,
      });
      await expect.poll(() => onSaved.mock.calls.length).toBe(1);
    });

    test("промт библиотеки — без пайплайна и retry, нельзя пропускать", async ({ api }) => {
      const { user } = renderForm(api, { mode: "library" });

      await user.type(screen.getByLabelText("Название"), "Ревью безопасности");
      await user.type(screen.getByLabelText(/Описание/), "Ищет уязвимости в diff");
      await user.type(screen.getByLabelText("Текст промта"), "Проверь diff");
      await user.click(save());

      expect(screen.queryByLabelText("Максимум попыток (retry)")).not.toBeInTheDocument();
      expect(savedBody(api)).toMatchObject({ pipeline_id: null, order_index: null, is_skipped: false });
      expect(savedBody(api)).not.toHaveProperty("max_retries");
      expect(savedBody(api)).not.toHaveProperty("retry_base_delay_seconds");
    });

    test.for([
      { mode: "library" as Mode, node: undefined, description: "  ", enabled: false },
      { mode: "library" as Mode, node: undefined, description: "Ищет уязвимости", enabled: true },
      { mode: "library" as Mode, node: makeNode({ is_library_item: true }), description: "", enabled: true },
      { mode: "pipeline" as Mode, node: undefined, description: "", enabled: true },
    ])(
      "$mode, правка: $node.id, описание «$description» → сохранить: $enabled",
      async ({ mode, node, description, enabled }, { api }) => {
        const { user } = renderForm(api, { mode, node });

        if (!node) await user.type(screen.getByLabelText("Название"), "Ревью");
        if (description) await user.type(screen.getByLabelText(/Описание/), description);

        expect(save()).toHaveProperty("disabled", !enabled);
      },
    );

    test("правка существующей ноды — PATCH по её id", async ({ api }) => {
      const { user } = renderForm(api, { node: makeNode({ id: "n7", order_index: 4 }) });

      await user.clear(screen.getByLabelText("Название"));
      await user.type(screen.getByLabelText("Название"), "Реализация с тестами");
      await user.click(save());

      expect(api.mutations()).toEqual([
        expect.objectContaining({ method: "PATCH", path: "/nodes/n7" }),
      ]);
      expect(savedBody(api)).toMatchObject({ name: "Реализация с тестами", order_index: 2, timeout_seconds: 600 });
    });

    test("ошибка сервера показывается уведомлением", async ({ api, toasts }) => {
      api.respond("POST /nodes", { error: { status: 422, message: "Неизвестная переменная {{node.nope}}" } });
      const { user, onSaved } = renderForm(api);

      await user.type(screen.getByLabelText("Название"), "Реализация");
      await user.click(save());

      await expect.poll(() => toasts.error.mock.calls).toEqual([["Неизвестная переменная {{node.nope}}"]]);
      expect(onSaved).not.toHaveBeenCalled();
    });
  });

  describe("таймаут и retry", () => {
    test("пока значения не меняли, новая нода берёт их из системных настроек", async ({ api }) => {
      const { user } = renderForm(api);

      const timeout = screen.getByLabelText("Таймаут (сек.)");
      await expect.poll(() => timeout.getAttribute("placeholder")).toBe("600");
      expect(timeout).toHaveValue(null);
      await user.type(screen.getByLabelText("Название"), "Реализация");
      await user.click(save());

      for (const field of ["timeout_seconds", "max_retries", "retry_base_delay_seconds"]) {
        expect(savedBody(api)).not.toHaveProperty(field);
      }
    });

    test("введённые значения уходят числами", async ({ api }) => {
      const { user } = renderForm(api);

      await user.type(screen.getByLabelText("Название"), "Реализация");
      for (const [label, value] of [
        ["Таймаут (сек.)", "1800"],
        ["Максимум попыток (retry)", "5"],
        ["Базовая задержка retry (сек.)", "0"],
      ]) {
        await user.clear(screen.getByLabelText(label));
        await user.type(screen.getByLabelText(label), value);
      }
      await user.click(screen.getByRole("checkbox", { name: "Пропускать по умолчанию" }));
      await user.click(save());

      expect(savedBody(api)).toMatchObject({
        timeout_seconds: 1800,
        max_retries: 5,
        retry_base_delay_seconds: 0,
        is_skipped: true,
      });
    });

    test.for([
      { label: "Таймаут (сек.)", field: "timeout_seconds" },
      { label: "Максимум попыток (retry)", field: "max_retries" },
      { label: "Базовая задержка retry (сек.)", field: "retry_base_delay_seconds" },
    ])("очищенное поле «$label» не уходит нулём", async ({ label, field }, { api }) => {
      const { user } = renderForm(api, { node: makeNode() });

      await user.clear(screen.getByLabelText(label));
      await user.click(save());

      expect(screen.getByLabelText(label)).toHaveValue(null);
      expect(savedBody(api)).not.toHaveProperty(field);
    });
  });
});
