import { screen, within } from "@testing-library/react";
import { describe, expect, vi } from "vitest";
import { TaskControlButtons } from "@/components/tasks/TaskControlButtons";
import { TaskStatus, type Task } from "@/lib/types";
import { makeTask } from "@/test/factories";
import { test } from "@/test/fixtures";
import { renderWithProviders } from "@/test/renderWithProviders";

/** Подписи кнопок шапки задачи (aria-label). */
const Button = {
  START: "Запустить задачу",
  CANCEL: "Отменить запуск",
  PAUSE: "Приостановить",
  RESUME: "Продолжить",
  STOP: "Остановить",
  RESTART: "Перезапустить с текущей ноды",
  CLEAR_CONTEXT: "Очистить контекст",
  CLEANUP: "Очистить репозитории",
  DUPLICATE: "Дублировать",
} as const;

const ALL_BUTTONS = Object.values(Button);

function renderButtons(overrides: Partial<Task>) {
  return renderWithProviders(<TaskControlButtons task={makeTask(overrides)} />);
}

function visibleButtons(): string[] {
  return ALL_BUTTONS.filter((name) => screen.queryByRole("button", { name }) !== null);
}

describe("TaskControlButtons", () => {
  describe("набор кнопок по статусу", () => {
    test.for([
      { status: TaskStatus.NEW, expected: [Button.START] },
      { status: TaskStatus.REFINING, expected: [Button.START] },
      { status: TaskStatus.DEFINED, expected: [Button.START] },
      { status: TaskStatus.READY, expected: [Button.START] },
      { status: TaskStatus.NIGHT_WORKER, expected: [Button.START] },
      { status: TaskStatus.QUEUED, expected: [Button.CANCEL] },
      { status: TaskStatus.IN_PROGRESS, expected: [Button.PAUSE, Button.STOP] },
      { status: TaskStatus.PAUSED, expected: [Button.RESUME, Button.STOP] },
      { status: TaskStatus.PLAN_REVIEW, expected: [] },
      { status: TaskStatus.AWAITING_INPUT, expected: [] },
      { status: TaskStatus.REBASE_CONFLICT, expected: [] },
      { status: TaskStatus.AWAITING_LIMIT, expected: [Button.STOP] },
      {
        status: TaskStatus.FAILED,
        expected: [Button.RESTART, Button.CLEAR_CONTEXT, Button.CLEANUP],
      },
      { status: TaskStatus.DONE, expected: [Button.CLEANUP, Button.DUPLICATE] },
    ])("$status", ({ status, expected }) => {
      renderButtons({ status });

      expect(visibleButtons()).toEqual(expected);
    });

    test.for([
      { pipeline_id: null, chat_active: false },
      { pipeline_id: "p1", chat_active: true },
    ])("«Запустить» неактивна: пайплайн $pipeline_id, чат $chat_active", (fields) => {
      renderButtons({ status: TaskStatus.REFINING, ...fields });

      expect(screen.getByRole("button", { name: Button.START })).toBeDisabled();
    });

    test.for([
      { from: TaskStatus.IN_PROGRESS, expected: [Button.PAUSE, Button.STOP] },
      { from: TaskStatus.REBASE_CONFLICT, expected: [Button.PAUSE, Button.STOP] },
      { from: TaskStatus.PAUSED, expected: [Button.STOP] },
      { from: TaskStatus.REFINING, expected: [Button.STOP] },
    ])("ждёт лимита из $from", ({ from, expected }) => {
      renderButtons({ status: TaskStatus.AWAITING_LIMIT, limit_wait_from_status: from });

      expect(visibleButtons()).toEqual(expected);
    });

    test.for([TaskStatus.FAILED, TaskStatus.DONE])(
      "%s: после очистки репозиториев кнопки нет, есть пометка",
      (status) => {
        renderButtons({ status, repo_cleaned_at: "2026-10-25T11:00:00Z" });

        expect(screen.queryByRole("button", { name: Button.CLEANUP })).not.toBeInTheDocument();
        expect(screen.getByText("Репозитории очищены")).toBeInTheDocument();
      },
    );
  });

  describe("действие без подтверждения", () => {
    test.for([
      { status: TaskStatus.NEW, button: Button.START, action: "start" },
      { status: TaskStatus.QUEUED, button: Button.CANCEL, action: "cancel" },
      { status: TaskStatus.IN_PROGRESS, button: Button.PAUSE, action: "pause" },
      { status: TaskStatus.PAUSED, button: Button.RESUME, action: "resume" },
      { status: TaskStatus.FAILED, button: Button.RESTART, action: "restart" },
    ])("$status: «$button» → POST /$action", async ({ status, button, action }, { api }) => {
      const { user } = renderButtons({ status });

      await user.click(screen.getByRole("button", { name: button }));

      expect(api.mutations()).toEqual([
        { method: "POST", path: `/tasks/t1/${action}`, body: undefined },
      ]);
    });
  });

  describe("действие с подтверждением", () => {
    const CONFIRMED_ACTIONS = [
      { status: TaskStatus.IN_PROGRESS, button: Button.STOP, confirm: "Остановить", action: "stop" },
      { status: TaskStatus.PAUSED, button: Button.STOP, confirm: "Остановить", action: "stop" },
      { status: TaskStatus.AWAITING_LIMIT, button: Button.STOP, confirm: "Остановить", action: "stop" },
      {
        status: TaskStatus.FAILED,
        button: Button.CLEAR_CONTEXT,
        confirm: "Очистить контекст",
        action: "clear-context",
      },
      {
        status: TaskStatus.FAILED,
        button: Button.CLEANUP,
        confirm: "Очистить",
        action: "cleanup-repositories",
      },
      {
        status: TaskStatus.DONE,
        button: Button.CLEANUP,
        confirm: "Очистить",
        action: "cleanup-repositories",
      },
    ];

    test.for(CONFIRMED_ACTIONS)(
      "$status: «$button» выполняется после подтверждения",
      async ({ status, button, confirm, action }, { api }) => {
        const { user } = renderButtons({ status });

        await user.click(screen.getByRole("button", { name: button }));
        expect(api.mutations()).toEqual([]);

        await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: confirm }));

        expect(api.mutations()).toEqual([
          { method: "POST", path: `/tasks/t1/${action}`, body: undefined },
        ]);
      },
    );

    test.for(CONFIRMED_ACTIONS)(
      "$status: отмена «$button» ничего не отправляет",
      async ({ status, button }, { api }) => {
        const { user } = renderButtons({ status });

        await user.click(screen.getByRole("button", { name: button }));
        await user.click(screen.getByRole("button", { name: "Отмена" }));

        expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
        expect(api.mutations()).toEqual([]);
      },
    );
  });

  describe("ответ сервера", () => {
    test.for([
      { status: TaskStatus.NEW, button: Button.START, action: "start", text: "Задача поставлена в очередь" },
      { status: TaskStatus.IN_PROGRESS, button: Button.PAUSE, action: "pause", text: "Пауза наступит после текущей ноды" },
      { status: TaskStatus.AWAITING_LIMIT, button: Button.PAUSE, action: "pause", text: "После сброса лимита задача встанет на паузу" },
    ])("$status: успех «$button» подтверждается уведомлением", async ({ status, button, text }, { toasts }) => {
      const { user } = renderButtons({ status, limit_wait_from_status: TaskStatus.IN_PROGRESS });

      await user.click(screen.getByRole("button", { name: button }));

      await expect.poll(() => toasts.success.mock.calls).toEqual([[text]]);
    });

    test("ошибка запуска показывает сообщение сервера", async ({ api, toasts }) => {
      api.respond("POST /tasks/t1/start", {
        error: { status: 422, message: "У задачи нет LLM-аккаунта" },
      });
      const { user } = renderButtons({ status: TaskStatus.NEW });

      await user.click(screen.getByRole("button", { name: Button.START }));

      await expect.poll(() => toasts.error.mock.calls).toEqual([["У задачи нет LLM-аккаунта"]]);
    });

    test("пока запуск отправляется, повторно нажать нельзя", async ({ api }) => {
      api.respond("POST /tasks/t1/start", () => new Promise(() => {}));
      const { user } = renderButtons({ status: TaskStatus.NEW });

      await user.click(screen.getByRole("button", { name: Button.START }));

      expect(screen.getByRole("button", { name: Button.START })).toBeDisabled();
      expect(api.mutations()).toHaveLength(1);
    });
  });

  describe("ожидание лимита", () => {
    const HINT = /Все LLM-аккаунты на пороге — задача начнёт работу в/;

    test.for([
      { status: TaskStatus.NEW, waitUntil: "2026-11-10T18:40:00Z", shown: true },
      { status: TaskStatus.NEW, waitUntil: null, shown: false },
      { status: TaskStatus.FAILED, waitUntil: "2026-11-10T18:40:00Z", shown: false },
    ])("$status, ожидание до $waitUntil — подсказка у запуска: $shown", async ({ status, waitUntil, shown }, { api }) => {
      api.respond("GET /tasks/llm-limit", { wait_until: waitUntil });
      renderButtons({ status });

      const asked = () => api.requests.some((request) => request.path === "/tasks/llm-limit");
      if (shown) expect(await screen.findByText(HINT)).toBeInTheDocument();
      else expect(screen.queryByText(HINT)).not.toBeInTheDocument();
      await expect.poll(asked).toBe(status === TaskStatus.NEW);
    });

    test("ожидание спрашивается у автора задачи, а не у смотрящего", async ({ api }) => {
      api.respond("GET /tasks/llm-limit", { wait_until: null });
      renderButtons({ status: TaskStatus.NEW, created_by: "author-7" });

      const askedUrls = () => vi.mocked(fetch).mock.calls.map(([input]) => String(input));
      await expect.poll(askedUrls).toContain("/api/tasks/llm-limit?author_id=author-7");
    });

    test("после запуска подсказки нет, хотя ожидание ещё в кеше", async ({ api }) => {
      api.respond("GET /tasks/llm-limit", { wait_until: "2026-11-10T18:40:00Z" });
      const { rerender } = renderButtons({ status: TaskStatus.NEW });
      expect(await screen.findByText(HINT)).toBeInTheDocument();

      rerender(<TaskControlButtons task={makeTask({ status: TaskStatus.IN_PROGRESS })} />);

      expect(screen.queryByText(HINT)).not.toBeInTheDocument();
    });

    test("остановка ожидания чата оставляет «Уточняется»", async () => {
      const { user } = renderButtons({
        status: TaskStatus.AWAITING_LIMIT,
        limit_wait_from_status: TaskStatus.REFINING,
      });

      await user.click(screen.getByRole("button", { name: Button.STOP }));

      expect(screen.getByRole("dialog")).toHaveTextContent(
        "Ожидание лимита прекратится, задача останется в статусе «Уточняется».",
      );
    });
  });
});
