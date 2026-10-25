import { screen, within } from "@testing-library/react";
import { describe, expect, vi } from "vitest";
import { TaskNodesCard } from "@/components/tasks/TaskNodesCard";
import { NodeLogStatus, NodeType, TaskStatus, type NodeLog, type TaskNodeItem } from "@/lib/types";
import { makeNodeLog, makeTask, makeTaskNode } from "@/test/factories";
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

function renderCard(
  api: MockedApi,
  {
    status = TaskStatus.NEW,
    nodes = [analysis, tests, report],
    nodeLogs = [],
  }: { status?: TaskStatus; nodes?: TaskNodeItem[]; nodeLogs?: NodeLog[] } = {},
) {
  api.respond(`GET ${NODES_PATH}`, nodes);
  const onChangePipeline = vi.fn();
  const view = renderWithProviders(
    <TaskNodesCard
      task={makeTask({ status })}
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
      { status: TaskStatus.NEW, hint: "Снимите галочку, чтобы пропустить ноду в этой задаче" },
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
});
