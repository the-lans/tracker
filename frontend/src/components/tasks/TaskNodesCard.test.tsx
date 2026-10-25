import { screen, within } from "@testing-library/react";
import { describe, expect, vi } from "vitest";
import { TaskNodesCard } from "@/components/tasks/TaskNodesCard";
import { NodeLogStatus, NodeType, TaskStatus, type NodeLog, type TaskNodeItem } from "@/lib/types";
import { makeNode, makeNodeLog, makeTask, makeTaskNode } from "@/test/factories";
import type { MockedApi } from "@/test/apiMock";
import { test } from "@/test/fixtures";
import { renderWithProviders } from "@/test/renderWithProviders";

const NODES_PATH = "/tasks/t1/nodes";

const analysis = makeTaskNode({
  id: "tn1",
  node_id: "n1",
  order_index: 0,
  name: "Анализ задачи",
  node_type: NodeType.PLAN_PROMPT,
});
const tests = makeTaskNode({
  id: "tn2",
  node_id: "n2",
  order_index: 1,
  name: "Тесты и линтеры",
  node_type: NodeType.SCRIPT,
});
const report = makeTaskNode({
  id: "tn3",
  node_id: "n3",
  order_index: 2,
  name: "Отчёт для MR",
  is_enabled: false,
});

function checkbox(name: string) {
  return screen.findByRole("checkbox", { name: `Включить ноду ${name}` });
}

function pauseButton(name: string) {
  return screen.findByRole("button", { name: `Пауза после ноды ${name}` });
}

function renderCard(
  api: MockedApi,
  {
    status = TaskStatus.NEW,
    lastFailed = null,
    nodes = [analysis, tests, report],
    nodeLogs = [],
  }: {
    status?: TaskStatus;
    lastFailed?: number | null;
    nodes?: TaskNodeItem[];
    nodeLogs?: NodeLog[];
  } = {},
) {
  api.respond(`GET ${NODES_PATH}`, nodes);
  const onChangePipeline = vi.fn();
  const view = renderWithProviders(
    <TaskNodesCard
      task={makeTask({ status, last_failed_order_index: lastFailed })}
      nodeLogs={nodeLogs}
      onChangePipeline={onChangePipeline}
    />,
  );
  return { ...view, onChangePipeline };
}

describe("TaskNodesCard", () => {
  describe("заголовок и подсказка", () => {
    test("в new пайплайн можно сменить", async ({ api }) => {
      const { user, onChangePipeline } = renderCard(api);

      await user.click(screen.getByRole("button", { name: "Сменить пайплайн" }));

      expect(onChangePipeline).toHaveBeenCalledOnce();
    });

    test("после запуска — счётчик выполненных из включённых", async ({ api }) => {
      renderCard(api, {
        status: TaskStatus.IN_PROGRESS,
        nodeLogs: [
          makeNodeLog({ id: "log1", node_id: "n1" }),
          makeNodeLog({ id: "log2", node_id: "n2", status: NodeLogStatus.RUNNING }),
        ],
      });

      expect(await screen.findByText("1 / 2")).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Сменить пайплайн" })).not.toBeInTheDocument();
      expect(screen.getByLabelText("выполнено")).toBeInTheDocument();
    });

    test.for([
      { status: TaskStatus.NEW, hint: /Снимите галочку.*кнопкой «\+ Промт»/ },
      { status: TaskStatus.FAILED, hint: /менять можно только ноды после точки сбоя/ },
      { status: TaskStatus.DONE, hint: /Задача завершена — чтобы сменить пайплайн/ },
      { status: TaskStatus.QUEUED, hint: "Состав нод заблокирован — задача уже запущена" },
      { status: TaskStatus.IN_PROGRESS, hint: "Состав нод заблокирован — задача уже запущена" },
      { status: TaskStatus.PAUSED, hint: "Состав нод заблокирован — задача уже запущена" },
    ])("$status: подсказка о правке состава", ({ status, hint }, { api }) => {
      renderCard(api, { status });

      expect(screen.getByText(hint)).toBeInTheDocument();
    });

    test("пустой пайплайн объясняет, что делать", async ({ api }) => {
      renderCard(api, { nodes: [] });

      expect(await screen.findByText("В пайплайне нет нод")).toBeInTheDocument();
    });
  });

  describe("доступность чекбоксов", () => {
    test.for([
      { editable: true, disabled: false },
      { editable: false, disabled: true },
    ])("editable=$editable → disabled=$disabled", async ({ editable, disabled }, { api }) => {
      renderCard(api, { status: TaskStatus.FAILED, nodes: [{ ...analysis, editable }] });

      const box = await checkbox(analysis.name);

      expect(box).toHaveProperty("disabled", disabled);
    });
  });

  describe("включение и отключение", () => {
    test("включение отправляется без проверки зависимых", async ({ api }) => {
      const { user } = renderCard(api);

      await user.click(await checkbox(report.name));

      expect(api.mutations()).toEqual([
        { method: "PATCH", path: `${NODES_PATH}/tn3`, body: { is_enabled: true } },
      ]);
      expect(api.requests.some((request) => request.path.endsWith("/dependents"))).toBe(false);
    });

    test("без зависимых нода отключается сразу", async ({ api }) => {
      api.respond(`GET ${NODES_PATH}/tn2/dependents`, []);
      const { user } = renderCard(api);

      await user.click(await checkbox(tests.name));

      await expect.poll(() => api.mutations()).toEqual([
        { method: "PATCH", path: `${NODES_PATH}/tn2`, body: { is_enabled: false } },
      ]);
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });

    test.for([
      { choice: "Всё равно отключить", sent: true },
      { choice: "Отмена", sent: false },
    ])("есть зависимые: «$choice»", async ({ choice, sent }, { api }) => {
      api.respond(`GET ${NODES_PATH}/tn1/dependents`, [
        { node_id: "n2", name: "Реализация" },
        { node_id: "n3", name: "Отчёт для MR" },
      ]);
      const { user } = renderCard(api);

      await user.click(await checkbox(analysis.name));
      const dialog = await screen.findByRole("dialog");

      expect(dialog).toHaveTextContent("На вывод ноды «Анализ задачи» ссылаются последующие ноды");
      expect(within(dialog).getAllByRole("listitem").map((item) => item.textContent)).toEqual([
        "Реализация",
        "Отчёт для MR",
      ]);
      expect(api.mutations()).toEqual([]);

      await user.click(within(dialog).getByRole("button", { name: choice }));

      expect(api.mutations()).toEqual(
        sent ? [{ method: "PATCH", path: `${NODES_PATH}/tn1`, body: { is_enabled: false } }] : [],
      );
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });

    test.for([
      { failing: "dependents", route: `GET ${NODES_PATH}/tn2/dependents`, message: "Нода не найдена" },
      { failing: "patch", route: `PATCH ${NODES_PATH}/tn2`, message: "Ноду уже нельзя менять" },
    ])("ошибка ($failing) показывается уведомлением", async ({ route, message }, { api, toasts }) => {
      api.respond(`GET ${NODES_PATH}/tn2/dependents`, []);
      api.respond(route, { error: { status: 409, message } });
      const { user } = renderCard(api);

      await user.click(await checkbox(tests.name));

      await expect.poll(() => toasts.error.mock.calls).toEqual([[message]]);
    });
  });

  describe("пауза после ноды", () => {
    test.for([TaskStatus.NEW, TaskStatus.IN_PROGRESS, TaskStatus.PAUSED, TaskStatus.FAILED])(
      "%s: отметка меняется и после запуска",
      async (status, { api }) => {
        const { user } = renderCard(api, { status, nodes: [{ ...analysis, editable: false }] });

        await user.click(await pauseButton(analysis.name));

        expect(api.mutations()).toEqual([
          { method: "PATCH", path: `${NODES_PATH}/tn1`, body: { pause_after: true } },
        ]);
      },
    );

    test.for([
      { pauseAfter: false, sent: true },
      { pauseAfter: true, sent: false },
    ])("pause_after=$pauseAfter → нажатие отправляет $sent", async ({ pauseAfter, sent }, { api }) => {
      const { user } = renderCard(api, { nodes: [{ ...tests, pause_after: pauseAfter }] });

      const button = await pauseButton(tests.name);
      expect(button).toHaveAttribute("aria-pressed", String(pauseAfter));
      await user.click(button);

      expect(api.mutations()).toEqual([
        { method: "PATCH", path: `${NODES_PATH}/tn2`, body: { pause_after: sent } },
      ]);
    });

    test("у очистки контекста паузы нет", async ({ api }) => {
      renderCard(api, {
        nodes: [makeTaskNode({ id: "tn4", name: "Сброс", node_type: NodeType.CLEAR_CONTEXT })],
      });

      expect(await checkbox("Сброс")).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Пауза после ноды Сброс" })).not.toBeInTheDocument();
    });

    test("ошибка показывается уведомлением", async ({ api, toasts }) => {
      api.respond(`PATCH ${NODES_PATH}/tn1`, { error: { status: 404, message: "Нода не найдена" } });
      const { user } = renderCard(api);

      await user.click(await pauseButton(analysis.name));

      await expect.poll(() => toasts.error.mock.calls).toEqual([["Нода не найдена"]]);
    });
  });

  describe("свои промты", () => {
    const custom = makeTaskNode({
      id: "tn9",
      node_id: "c9",
      order_index: 1,
      name: "Вопросы по задаче",
      is_custom: true,
      prompt_template: "Задай вопросы по {{task.code}}",
    });

    function insertButtons() {
      return screen
        .queryAllByRole("button", { name: /^Вставить свой промт/ })
        .map((button) => button.getAttribute("aria-label"));
    }

    async function openInsertAfter(user: ReturnType<typeof renderCard>["user"], name: string) {
      await user.click(
        await screen.findByRole("button", { name: `Вставить свой промт после ноды ${name}` }),
      );
      return screen.getByRole("dialog");
    }

    test.for([
      {
        status: TaskStatus.NEW,
        lastFailed: null,
        after: ["в начало", "после ноды Анализ задачи", "после ноды Тесты и линтеры", "после ноды Отчёт для MR"],
      },
      {
        status: TaskStatus.FAILED,
        lastFailed: 0,
        after: ["после ноды Анализ задачи", "после ноды Тесты и линтеры", "после ноды Отчёт для MR"],
      },
      { status: TaskStatus.FAILED, lastFailed: 2, after: ["после ноды Отчёт для MR"] },
      { status: TaskStatus.IN_PROGRESS, lastFailed: null, after: [] },
      { status: TaskStatus.DONE, lastFailed: null, after: [] },
    ])("$status, сбой на $lastFailed → «+ Промт» $after", async ({ status, lastFailed, after }, { api }) => {
      renderCard(api, { status, lastFailed });
      await checkbox(analysis.name);

      expect(insertButtons()).toEqual(after.map((place) => `Вставить свой промт ${place}`));
    });

    test("вставка промта после ноды", async ({ api }) => {
      api.respond(`POST ${NODES_PATH}`, custom);
      const { user } = renderCard(api);

      const dialog = await openInsertAfter(user, analysis.name);
      await user.type(within(dialog).getByLabelText("Название"), "Вопросы");
      await user.type(within(dialog).getByLabelText("Текст промта"), "Задай вопросы");
      await user.click(within(dialog).getByRole("button", { name: "Сохранить" }));

      expect(api.mutations()).toEqual([
        {
          method: "POST",
          path: NODES_PATH,
          body: {
            name: "Вопросы",
            node_type: NodeType.PLAIN_PROMPT,
            prompt_template: "Задай вопросы",
            command_invocation: null,
            after_task_node_id: "tn1",
          },
        },
      ]);
      await expect.poll(() => screen.queryByRole("dialog")).toBeNull();
    });

    test("слэш-команда уходит буквально, без текста промта", async ({ api }) => {
      const { user } = renderCard(api);

      const dialog = await openInsertAfter(user, tests.name);
      await user.type(within(dialog).getByLabelText("Название"), "Ревью");
      await user.click(within(dialog).getByRole("combobox", { name: "Тип" }));
      await user.click(await screen.findByRole("option", { name: "Слэш-команда" }));
      await user.type(within(dialog).getByLabelText("Слэш-команда"), "/review");
      await user.click(within(dialog).getByRole("button", { name: "Сохранить" }));

      expect(api.mutations()[0]?.body).toEqual({
        name: "Ревью",
        node_type: NodeType.SLASH_COMMAND,
        prompt_template: null,
        command_invocation: "/review",
        after_task_node_id: "tn2",
      });
    });

    test("«Заполнить из библиотеки» копирует промт", async ({ api }) => {
      api.respond("GET /nodes", [
        makeNode({
          id: "l1",
          pipeline_id: null,
          is_library_item: true,
          name: "Вопросы перед реализацией",
          prompt_template: "Составь список вопросов",
        }),
        makeNode({ id: "l2", pipeline_id: null, is_library_item: true, name: "Линтер", node_type: NodeType.SCRIPT }),
      ]);
      const { user } = renderCard(api);

      const dialog = await openInsertAfter(user, analysis.name);
      await user.click(await within(dialog).findByRole("combobox", { name: "Заполнить из библиотеки" }));
      const options = await screen.findAllByRole("option");
      expect(options.map((option) => option.textContent)).toEqual(["Вопросы перед реализацией"]);
      await user.click(options[0]!);

      expect(within(dialog).getByLabelText("Название")).toHaveValue("Вопросы перед реализацией");
      expect(within(dialog).getByLabelText("Текст промта")).toHaveValue("Составь список вопросов");
    });

    test("ошибка сохранения оставляет диалог открытым", async ({ api, toasts }) => {
      api.respond(`POST ${NODES_PATH}`, { error: { status: 422, message: "Неизвестная переменная" } });
      const { user } = renderCard(api);

      const dialog = await openInsertAfter(user, analysis.name);
      await user.type(within(dialog).getByLabelText("Название"), "Вопросы");
      await user.type(within(dialog).getByLabelText("Текст промта"), "x");
      await user.click(within(dialog).getByRole("button", { name: "Сохранить" }));

      await expect.poll(() => toasts.error.mock.calls).toEqual([["Неизвестная переменная"]]);
      expect(screen.getByRole("dialog")).toBeInTheDocument();
    });

    test("правка своего промта отправляет новое содержимое", async ({ api }) => {
      const { user } = renderCard(api, { nodes: [analysis, custom] });

      await user.click(await screen.findByRole("button", { name: `Изменить промт ${custom.name}` }));
      const dialog = screen.getByRole("dialog");
      const text = within(dialog).getByLabelText("Текст промта");
      expect(text).toHaveValue("Задай вопросы по {{task.code}}");
      await user.type(text, " и CSV");
      await user.click(within(dialog).getByRole("button", { name: "Сохранить" }));

      expect(api.mutations()).toEqual([
        {
          method: "PATCH",
          path: `${NODES_PATH}/tn9`,
          body: {
            content: {
              name: "Вопросы по задаче",
              node_type: NodeType.PLAIN_PROMPT,
              prompt_template: "Задай вопросы по {{task.code}} и CSV",
              command_invocation: null,
            },
          },
        },
      ]);
    });

    test("удаление — после подтверждения", async ({ api }) => {
      const { user } = renderCard(api, { nodes: [analysis, custom] });

      await user.click(await screen.findByRole("button", { name: `Удалить промт ${custom.name}` }));
      expect(api.mutations()).toEqual([]);
      await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Удалить" }));

      expect(api.mutations()).toEqual([{ method: "DELETE", path: `${NODES_PATH}/tn9`, body: undefined }]);
      await expect.poll(() => screen.queryByRole("dialog")).toBeNull();
    });

    test.for([
      { editable: true, actions: true },
      { editable: false, actions: false },
    ])("редактируемый $editable → «Изменить»/«Удалить»: $actions", async ({ editable, actions }, { api }) => {
      renderCard(api, { nodes: [{ ...custom, editable }] });

      expect(await screen.findByText("свой промт")).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: `Удалить промт ${custom.name}` }) !== null).toBe(actions);
      expect(screen.queryByRole("button", { name: `Изменить промт ${custom.name}` }) !== null).toBe(actions);
    });
  });
});
