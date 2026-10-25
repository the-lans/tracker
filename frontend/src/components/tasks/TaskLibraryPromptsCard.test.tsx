import { screen, within } from "@testing-library/react";
import { describe, expect } from "vitest";
import { TaskLibraryPromptsCard } from "@/components/tasks/TaskLibraryPromptsCard";
import {
  LibraryPromptRunStatus,
  NodeType,
  TaskStatus,
  type NodeItem,
  type Task,
  type TaskLibraryPromptItem,
} from "@/lib/types";
import { makeLibraryPrompt, makeNode, makeTask } from "@/test/factories";
import type { MockedApi } from "@/test/apiMock";
import { test } from "@/test/fixtures";
import { renderWithProviders } from "@/test/renderWithProviders";

const PROMPTS_PATH = "/tasks/t1/library-prompts";
const NO_SESSION = "Сессия задачи не активна";
const NO_LLM_ACCOUNT = "У задачи нет LLM-аккаунта — доступны только скрипты";

const libraryNodes: NodeItem[] = [
  makeNode({ id: "l1", pipeline_id: null, name: "Ревью безопасности", is_library_item: true }),
  makeNode({ id: "l2", pipeline_id: null, name: "Прогнать e2e-тесты", is_library_item: true }),
];

function renderCard(
  api: MockedApi,
  prompts: TaskLibraryPromptItem[],
  task: Partial<Task> = { status: TaskStatus.IN_PROGRESS },
) {
  api.respond(`GET ${PROMPTS_PATH}`, prompts);
  return renderWithProviders(
    <TaskLibraryPromptsCard task={makeTask(task)} libraryNodes={libraryNodes} />,
  );
}

const runButton = () => screen.findByRole("button", { name: "Выполнить промт" });
const stopButton = () => screen.findByRole("button", { name: "Остановить промт" });

describe("TaskLibraryPromptsCard", () => {
  describe("запуск ▶", () => {
    test.for([
      { status: TaskStatus.IN_PROGRESS, llm: "acc1", type: NodeType.PLAIN_PROMPT, reason: null },
      { status: TaskStatus.PAUSED, llm: "acc1", type: NodeType.SLASH_COMMAND, reason: null },
      { status: TaskStatus.PLAN_REVIEW, llm: "acc1", type: NodeType.PLAIN_PROMPT, reason: null },
      { status: TaskStatus.AWAITING_INPUT, llm: "acc1", type: NodeType.SCRIPT, reason: null },
      { status: TaskStatus.REBASE_CONFLICT, llm: "acc1", type: NodeType.PLAIN_PROMPT, reason: null },
      { status: TaskStatus.IN_PROGRESS, llm: null, type: NodeType.SCRIPT, reason: null },
      { status: TaskStatus.IN_PROGRESS, llm: null, type: NodeType.PLAIN_PROMPT, reason: NO_LLM_ACCOUNT },
      { status: TaskStatus.IN_PROGRESS, llm: null, type: NodeType.SLASH_COMMAND, reason: NO_LLM_ACCOUNT },
      { status: TaskStatus.NEW, llm: "acc1", type: NodeType.PLAIN_PROMPT, reason: NO_SESSION },
      { status: TaskStatus.QUEUED, llm: "acc1", type: NodeType.SCRIPT, reason: NO_SESSION },
      { status: TaskStatus.FAILED, llm: "acc1", type: NodeType.PLAIN_PROMPT, reason: NO_SESSION },
      { status: TaskStatus.DONE, llm: null, type: NodeType.SCRIPT, reason: NO_SESSION },
    ])(
      "$status, аккаунт $llm, $type → $reason",
      async ({ status, llm, type, reason }, { api }) => {
        renderCard(api, [makeLibraryPrompt({ node_type: type })], { status, llm_account_id: llm });

        const button = await runButton();

        expect(button).toHaveProperty("disabled", reason !== null);
        expect(button).toHaveAttribute("title", reason ?? "Выполнить");
      },
    );

    test("▶ ставит промт на выполнение", async ({ api, toasts }) => {
      const { user } = renderCard(api, [makeLibraryPrompt()]);

      await user.click(await runButton());

      expect(api.mutations()).toEqual([
        { method: "POST", path: `${PROMPTS_PATH}/lp1/run`, body: undefined },
      ]);
      await expect.poll(() => toasts.success.mock.calls).toEqual([["Промт поставлен на выполнение"]]);
    });

    test("ошибка запуска показывается уведомлением", async ({ api, toasts }) => {
      api.respond(`POST ${PROMPTS_PATH}/lp1/run`, {
        error: { status: 409, message: "Промт уже в очереди" },
      });
      const { user } = renderCard(api, [makeLibraryPrompt()]);

      await user.click(await runButton());

      await expect.poll(() => toasts.error.mock.calls).toEqual([["Промт уже в очереди"]]);
    });
  });

  describe("остановка ■", () => {
    test.for([
      { state: "в очереди", status: LibraryPromptRunStatus.QUEUED, request: "mq1", enabled: true },
      { state: "выполняется", status: LibraryPromptRunStatus.RUNNING, request: "mq1", enabled: true },
      { state: "без запроса", status: LibraryPromptRunStatus.SUCCESS, request: null, enabled: false },
    ])("$state → ■ активна: $enabled", async ({ status, request, enabled }, { api }) => {
      renderCard(api, [makeLibraryPrompt({ last_run_status: status, active_request_id: request })]);

      expect(await stopButton()).toHaveProperty("disabled", !enabled);
    });

    test("■ останавливает активный запрос", async ({ api }) => {
      const { user } = renderCard(api, [makeLibraryPrompt({ last_run_status: LibraryPromptRunStatus.RUNNING, active_request_id: "mq7" })]);

      await user.click(await stopButton());

      expect(api.mutations()).toEqual([
        { method: "POST", path: "/tasks/t1/manual-queue/mq7/stop", body: undefined },
      ]);
    });
  });

  describe("строка промта", () => {
    test.for([
      { status: LibraryPromptRunStatus.NEVER_RUN, label: "не запускался" },
      { status: LibraryPromptRunStatus.QUEUED, label: "в очереди" },
      { status: LibraryPromptRunStatus.RUNNING, label: "выполняется" },
      { status: LibraryPromptRunStatus.SUCCESS, label: "успех" },
      { status: LibraryPromptRunStatus.FAILED, label: "ошибка" },
      { status: LibraryPromptRunStatus.STOPPED, label: "остановлен" },
    ])("статус $status → «$label»", async ({ status, label }, { api }) => {
      renderCard(api, [makeLibraryPrompt({ last_run_status: status })]);

      expect(await screen.findByText(label)).toBeInTheDocument();
    });

    test.for([
      { lastRunAt: "2026-10-25T11:59:00Z", shown: true },
      { lastRunAt: null, shown: false },
    ])("время запуска $lastRunAt показано: $shown", async ({ lastRunAt, shown }, { api }) => {
      renderCard(api, [makeLibraryPrompt({ last_run_at: lastRunAt })]);
      await screen.findByText("Ревью безопасности");

      expect(screen.queryByText(/25\.10\.26/) !== null).toBe(shown);
    });

    test("без промтов — подсказка, как добавить", async ({ api }) => {
      renderCard(api, []);

      expect(await screen.findByText("Промты из библиотеки не добавлены")).toBeInTheDocument();
    });
  });

  describe("добавление из библиотеки", () => {
    test("«Добавить» активна только после выбора промта", async ({ api }) => {
      const { user } = renderCard(api, []);

      await user.click(screen.getByRole("button", { name: "Добавить промт из библиотеки" }));
      const dialog = screen.getByRole("dialog");
      const addButton = within(dialog).getByRole("button", { name: "Добавить" });
      expect(addButton).toBeDisabled();

      await user.click(within(dialog).getByRole("combobox"));
      await user.click(await screen.findByRole("option", { name: "Прогнать e2e-тесты" }));
      await user.click(addButton);

      expect(api.mutations()).toEqual([{ method: "POST", path: PROMPTS_PATH, body: { node_id: "l2" } }]);
      await expect.poll(() => screen.queryByRole("dialog")).toBeNull();
    });

    test("пустая библиотека объясняет, где завести промт", async ({ api }) => {
      api.respond(`GET ${PROMPTS_PATH}`, []);
      const { user } = renderWithProviders(
        <TaskLibraryPromptsCard task={makeTask({ status: TaskStatus.IN_PROGRESS })} libraryNodes={[]} />,
      );

      await user.click(screen.getByRole("button", { name: "Добавить промт из библиотеки" }));

      expect(screen.getByText("В библиотеке пока нет промтов")).toBeInTheDocument();
    });
  });
});
