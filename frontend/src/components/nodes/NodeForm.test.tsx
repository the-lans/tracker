import { screen } from "@testing-library/react";
import { describe, expect, vi } from "vitest";
import { NodeForm } from "@/components/nodes/NodeForm";
import { NodeType, ReasoningEffort, ScriptLanguage, type NodeItem } from "@/lib/types";
import type { MockedApi } from "@/test/apiMock";
import { makeNode } from "@/test/factories";
import { test } from "@/test/fixtures";
import { renderWithProviders } from "@/test/renderWithProviders";

type Mode = "pipeline" | "library";

function renderForm(
  api: MockedApi,
  { mode = "pipeline" as Mode, node }: { mode?: Mode; node?: NodeItem } = {},
) {
  api.respond("GET /system-settings", {
    default_timeout_seconds: 600,
    default_max_retries: 3,
    default_retry_base_delay_seconds: 5,
  });
  const onSaved = vi.fn();
  const view = renderWithProviders(
    <NodeForm
      mode={mode}
      pipelineId={mode === "pipeline" ? "p1" : undefined}
      pipelineOwnerId={mode === "pipeline" ? "u1" : undefined}
      orderIndex={2}
      node={node}
      onSaved={onSaved}
      onCancel={() => {}}
    />,
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
      { type: "library_prompt", label: "Промт из библиотеки", field: "Промт библиотеки" },
    ])("$type → поле «$field», чужих полей нет", async ({ label, field }, { api }) => {
      const { user } = renderForm(api);

      await chooseType(user, label);

      const all = ["Текст промта", "Слэш-команда", "Содержимое скрипта", "Промт библиотеки"];
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
        library_node_id: null,
        library_arguments: null,
        timeout_seconds: null,
        max_retries: null,
        retry_base_delay_seconds: null,
        is_skipped: false,
        reasoning_effort: null,
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
      { mode: "library" as Mode, editing: false, description: "  ", enabled: false },
      { mode: "library" as Mode, editing: false, description: "Ищет уязвимости", enabled: true },
      { mode: "library" as Mode, editing: true, description: "", enabled: true },
      { mode: "pipeline" as Mode, editing: false, description: "", enabled: true },
    ])(
      "$mode, правка: $editing, описание «$description» → сохранить: $enabled",
      async ({ mode, editing, description, enabled }, { api }) => {
        const node = editing ? makeNode({ is_library_item: true }) : undefined;
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

      expect(savedBody(api)).toMatchObject({
        timeout_seconds: null,
        max_retries: null,
        retry_base_delay_seconds: null,
      });
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
    ])("очищенное поле «$label» просит значение по умолчанию", async ({ label, field }, { api }) => {
      const { user } = renderForm(api, { node: makeNode() });

      await user.clear(screen.getByLabelText(label));
      await user.click(save());

      expect(screen.getByLabelText(label)).toHaveValue(null);
      expect(savedBody(api)).toHaveProperty(field, null);
    });
  });

  describe("уровень рассуждений", () => {
    test.for([
      { label: "Обычный промт", shown: true },
      { label: "Слэш-команда", shown: true },
      { label: "Режим планирования", shown: true },
      { label: "Скрипт", shown: false },
      { label: "Очистить контекст", shown: false },
    ])("«$label» → поле есть: $shown", async ({ label, shown }, { api }) => {
      const { user } = renderForm(api);

      await chooseType(user, label);

      expect(screen.queryByLabelText("Уровень рассуждений") !== null).toBe(shown);
    });

    test("выбранный уровень уходит с нодой", async ({ api }) => {
      const { user } = renderForm(api);

      await user.type(screen.getByLabelText("Название"), "Реализация");
      await user.click(screen.getByRole("combobox", { name: "Уровень рассуждений" }));
      await user.click(await screen.findByRole("option", { name: "максимальный" }));
      await user.click(save());

      expect(savedBody(api)).toMatchObject({ reasoning_effort: ReasoningEffort.MAX });
    });

    test("«По умолчанию аккаунта» очищает уровень ноды", async ({ api }) => {
      const { user } = renderForm(api, { node: makeNode({ reasoning_effort: ReasoningEffort.LOW }) });

      await user.click(screen.getByRole("combobox", { name: "Уровень рассуждений" }));
      await user.click(await screen.findByRole("option", { name: "По умолчанию аккаунта" }));
      await user.click(save());

      expect(savedBody(api)).toMatchObject({ reasoning_effort: null });
    });

    test("у скрипта уровень не отправляется", async ({ api }) => {
      const { user } = renderForm(api, { node: makeNode({ reasoning_effort: ReasoningEffort.LOW }) });

      await chooseType(user, "Скрипт");
      await user.click(save());

      expect(savedBody(api)).toMatchObject({ reasoning_effort: null });
    });
  });
});


describe("Команды библиотечных промтов", () => {
  test("сохраняет имя команды и подсказку", async ({ api }) => {
    const { user } = renderForm(api, { mode: "library" });
    await user.type(screen.getByLabelText("Название"), "Ревью");
    await user.type(screen.getByLabelText("Описание"), "Проверить изменения");
    await user.type(screen.getByLabelText("Slash-команда"), "/review");
    await user.type(screen.getByLabelText("Подсказка аргументов"), "[[сервис]");
    await user.click(screen.getByRole("button", {name: "Сохранить"}));
    expect(api.mutations()[0].body).toMatchObject({slash_name: "/review", argument_hint: "[сервис]"});
  });

  test("очистка имени удаляет команду и подсказку", async ({ api }) => {
    const { user } = renderForm(api, { mode: "library", node: makeNode({
      pipeline_id: null, is_library_item: true, slash_name: "review", argument_hint: "[сервис]",
    }) });
    await user.clear(screen.getByLabelText("Slash-команда"));
    await user.click(screen.getByRole("button", {name: "Сохранить"}));
    expect(api.mutations()[0].body).toMatchObject({slash_name: null, argument_hint: null});
  });

  test.for([
    { title: "команда библиотеки — аргументы уходят в запрос", mode: "library" as Mode, slash: "review", sent: "svc \"two words\"" },
    { title: "промт без команды — поля аргументов нет", mode: "library" as Mode, slash: null, sent: undefined },
    { title: "нода пайплайна — поля аргументов нет", mode: "pipeline" as Mode, slash: null, sent: undefined },
  ])("$title", async ({ mode, slash, sent }, { api }) => {
    api.respond("POST /templates/preview", { rendered_text: "Проверь svc" });
    const { user } = renderForm(api, { mode, node: makeNode({
      pipeline_id: mode === "pipeline" ? "p1" : null,
      is_library_item: mode === "library",
      node_type: NodeType.PLAIN_PROMPT,
      prompt_template: "Проверь $1",
      slash_name: slash,
      argument_hint: slash ? "[сервис]" : null,
    }) });

    const field = screen.queryByLabelText("Аргументы для предпросмотра");
    expect(field !== null).toBe(sent !== undefined);
    if (field) {
      expect(field).toHaveAttribute("placeholder", "[сервис]");
      await user.type(field, sent ?? "");
    }
    await user.click(screen.getByRole("button", { name: "Предпросмотр" }));

    expect(await screen.findByText("Проверь svc")).toBeInTheDocument();
    expect((api.mutations().at(-1)?.body as { arguments?: string }).arguments).toBe(sent);
  });
});

describe("гайд", () => {
  test.for([
    { mode: "pipeline" as Mode, label: "Обычный промт", shown: true },
    { mode: "pipeline" as Mode, label: "Режим планирования", shown: false },
    { mode: "pipeline" as Mode, label: "Слэш-команда", shown: false },
    { mode: "pipeline" as Mode, label: "Скрипт", shown: false },
    { mode: "library" as Mode, label: "Обычный промт", shown: true },
    { mode: "library" as Mode, label: "Скрипт", shown: false },
  ])("$mode, «$label» → поле гайда: $shown", async ({ mode, label, shown }, { api }) => {
    const { user } = renderForm(api, { mode });

    await chooseType(user, label);

    expect(screen.queryByLabelText("Гайд (URL Confluence)") !== null).toBe(shown);
    expect(screen.queryAllByText(/\{\{node\.guide_url\}\}/).length > 0).toBe(shown);
  });

  test("у не-промта гайд не отправляется, даже если был введён", async ({ api }) => {
    const { user } = renderForm(api);

    await user.type(screen.getByLabelText("Название"), "Сборка");
    await user.type(screen.getByLabelText("Гайд (URL Confluence)"), "https://wiki.example.com/x");
    await chooseType(user, "Скрипт");
    await user.click(save());

    expect(savedBody(api)).toMatchObject({ node_type: NodeType.SCRIPT, guide_url: null });
  });

  test("предпросмотр получает гайд промта", async ({ api }) => {
    api.respond("POST /templates/preview", { rendered_text: "ok" });
    const { user } = renderForm(api);

    await user.type(screen.getByLabelText("Текст промта"), "См. гайд");
    await user.type(screen.getByLabelText("Гайд (URL Confluence)"), "https://wiki.example.com/g");
    await user.click(screen.getByRole("button", { name: /Предпросмотр/ }));

    await expect
      .poll(() => api.requests.find((request) => request.path === "/templates/preview")?.body)
      .toMatchObject({ guide_url: "https://wiki.example.com/g" });
  });
});

describe("промт из библиотеки", () => {
  const review = makeNode({
    id: "lib-review",
    pipeline_id: null,
    order_index: null,
    is_library_item: true,
    name: "Ревью",
    slash_name: "review",
    argument_hint: "[сервис]",
    description: "Проверяет diff",
    prompt_template: "Проверь $1",
    guide_url: "https://wiki.example.com/review",
    revision: 3,
  });
  const library = [
    review,
    makeNode({ id: "lib-lint", pipeline_id: null, is_library_item: true, name: "Линт", node_type: NodeType.SCRIPT, script_language: ScriptLanguage.BASH, script_content: "ruff check" }),
    makeNode({ id: "lib-old", pipeline_id: null, is_library_item: true, name: "Старый", is_archived: true }),
    makeNode({ id: "lib-alien", pipeline_id: null, is_library_item: true, name: "Чужой", created_by: "u2" }),
  ];

  async function chooseLibrary(user: ReturnType<typeof renderForm>["user"], item: string) {
    await chooseType(user, "Промт из библиотеки");
    await user.click(screen.getByRole("combobox", { name: "Промт библиотеки" }));
    await user.click(await screen.findByRole("option", { name: item }));
  }

  test("в списке — промты автора пайплайна без архивных", async ({ api }) => {
    api.respond("GET /nodes", library);
    const { user } = renderForm(api);

    await chooseType(user, "Промт из библиотеки");
    await user.click(screen.getByRole("combobox", { name: "Промт библиотеки" }));

    expect((await screen.findAllByRole("option")).map((option) => option.textContent)).toEqual([
      "Ревью (/review)",
      "Линт",
    ]);
  });

  test("выбор скрывает свои поля и показывает промт; уходит ссылка с аргументами", async ({ api }) => {
    api.respond("GET /nodes", library);
    const { user } = renderForm(api);

    await user.type(screen.getByLabelText("Название"), "Ревью сервиса");
    await chooseLibrary(user, "Ревью (/review)");
    await user.type(screen.getByLabelText("Аргументы"), "billing");

    expect(screen.getByRole("combobox", { name: "Тип ноды" })).toHaveTextContent("Промт из библиотеки");
    expect(screen.queryByLabelText("Текст промта")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Гайд (URL Confluence)")).not.toBeInTheDocument();
    expect(screen.getByText("Проверь $1")).toBeInTheDocument();
    expect(screen.getByText(/версия 3/)).toBeInTheDocument();
    expect(screen.getByLabelText("Аргументы")).toHaveAttribute("placeholder", "[сервис]");

    await user.click(save());

    expect(savedBody(api)).toMatchObject({
      node_type: NodeType.PLAIN_PROMPT,
      library_node_id: "lib-review",
      library_arguments: "billing",
      prompt_template: null,
      guide_url: null,
    });
  });

  test("тип ноды — тип выбранного промта", async ({ api }) => {
    api.respond("GET /nodes", library);
    const { user } = renderForm(api);

    await user.type(screen.getByLabelText("Название"), "Линт");
    await chooseLibrary(user, "Линт");
    await user.click(save());

    expect(savedBody(api)).toMatchObject({
      node_type: NodeType.SCRIPT,
      library_node_id: "lib-lint",
      library_arguments: null,
      reasoning_effort: null,
    });
  });

  test("без выбранного промта сохранить нельзя", async ({ api }) => {
    api.respond("GET /nodes", library);
    const { user } = renderForm(api);

    await user.type(screen.getByLabelText("Название"), "Ревью");
    await chooseType(user, "Промт из библиотеки");

    expect(save()).toHaveProperty("disabled", true);
  });

  test("архивный промт остаётся у ноды, которая на него ссылается", async ({ api }) => {
    api.respond("GET /nodes", library);
    renderForm(api, {
      node: makeNode({ id: "n5", library_node_id: "lib-old", library_arguments: "x", prompt_template: null }),
    });

    expect(await screen.findByText("в архиве")).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Тип ноды" })).toHaveTextContent("Промт из библиотеки");
    expect(screen.getByLabelText("Аргументы")).toHaveValue("x");
  });

  test("другой тип ноды снимает ссылку", async ({ api }) => {
    api.respond("GET /nodes", library);
    const { user } = renderForm(api, {
      node: makeNode({ id: "n5", library_node_id: "lib-review", prompt_template: null }),
    });

    await chooseType(user, "Обычный промт");
    await user.type(screen.getByLabelText("Текст промта"), "Свой");
    await user.click(save());

    expect(savedBody(api)).toMatchObject({
      library_node_id: null,
      library_arguments: null,
      prompt_template: "Свой",
    });
  });

  test("в пайплайне — последний тип в списке", async ({ api }) => {
    const { user } = renderForm(api);

    await user.click(screen.getByRole("combobox", { name: "Тип ноды" }));

    expect((await screen.findAllByRole("option")).at(-1)).toHaveTextContent("Промт из библиотеки");
  });
});
