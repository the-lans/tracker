import { screen } from "@testing-library/react";
import { describe, expect } from "vitest";
import { TaskCard } from "@/components/tasks/TaskCard";
import { TaskStatus, UserRole, type Task } from "@/lib/types";
import { makeCurrentUser, makeTask, makeUser } from "@/test/factories";
import { test } from "@/test/fixtures";
import { renderWithProviders } from "@/test/renderWithProviders";

function renderCard(task: Partial<Task>, currentUser = makeCurrentUser()) {
  return renderWithProviders(<TaskCard task={makeTask(task)} />, { currentUser });
}

const START = { name: "Запустить задачу" };

describe("TaskCard", () => {
  test("код и название ведут на страницу задачи", () => {
    renderCard({});

    expect(screen.getByRole("link", { name: "RR-12345" })).toHaveAttribute("href", "/tasks/t1");
    expect(screen.getByRole("link", { name: "Экспорт отчётов в CSV" })).toHaveAttribute("href", "/tasks/t1");
  });

  describe("подпись под названием", () => {
    test.for([
      { task: { status: TaskStatus.NEW, pipeline_id: null }, text: "Пайплайн не выбран" },
      { task: { status: TaskStatus.FAILED, last_failed_order_index: 0 }, text: "Сбой на ноде №1" },
      { task: { status: TaskStatus.FAILED, last_failed_order_index: 2 }, text: "Сбой на ноде №3" },
      { task: { status: TaskStatus.QUEUED, scheduled_start_at: "2026-10-25T09:30:00" }, text: "старт в 09:30" },
    ])("$text", ({ task, text }) => {
      renderCard(task);

      expect(screen.getByText(text)).toBeInTheDocument();
    });

    test.for([
      { status: TaskStatus.NEW, pipeline_id: "p1", last_failed_order_index: null },
      { status: TaskStatus.FAILED, pipeline_id: "p1", last_failed_order_index: null },
      { status: TaskStatus.DONE, pipeline_id: null, last_failed_order_index: 1 },
    ])("$status без повода — без подписи", (task) => {
      renderCard(task);

      expect(screen.queryByText(/Пайплайн не выбран|Сбой на ноде|старт в/)).not.toBeInTheDocument();
    });
  });

  describe("быстрый запуск", () => {
    test.for(Object.values(TaskStatus).filter((status) => status !== TaskStatus.NEW))(
      "%s — кнопки запуска нет",
      (status) => {
        renderCard({ status });

        expect(screen.queryByRole("button", START)).not.toBeInTheDocument();
      },
    );

    test("без пайплайна запускать нечего", () => {
      renderCard({ status: TaskStatus.NEW, pipeline_id: null });

      expect(screen.getByRole("button", START)).toBeDisabled();
    });

    test("запуск отправляет start", async ({ api }) => {
      const { user } = renderCard({ status: TaskStatus.NEW });

      await user.click(screen.getByRole("button", START));

      expect(api.mutations()).toEqual([{ method: "POST", path: "/tasks/t1/start", body: undefined }]);
    });

    test("ошибка запуска — уведомление с причиной", async ({ api, toasts }) => {
      api.respond("POST /tasks/t1/start", {
        error: { status: 422, message: "У задачи нет LLM-аккаунта — доступны только скрипты" },
      });
      const { user } = renderCard({ status: TaskStatus.NEW });

      await user.click(screen.getByRole("button", START));

      await expect.poll(() => toasts.error.mock.calls).toEqual([
        ["У задачи нет LLM-аккаунта — доступны только скрипты"],
      ]);
    });
  });

  describe("автор (раздел 19.2)", () => {
    test("admin видит автора чужой задачи", async ({ api }) => {
      api.respond("GET /users", [makeUser({ id: "u2", email: "oleg@example.com" })]);
      renderCard({ created_by: "u2" }, makeCurrentUser({ role: UserRole.ADMIN }));

      expect(await screen.findByText("Автор: oleg@example.com")).toBeInTheDocument();
    });

    test.for([
      { role: UserRole.ADMIN, author: "u1" },
      { role: UserRole.USER, author: "u2" },
    ])("$role, автор $author — без подписи", ({ role, author }) => {
      renderCard({ created_by: author }, makeCurrentUser({ role }));

      expect(screen.queryByText(/Автор:/)).not.toBeInTheDocument();
    });
  });
});
