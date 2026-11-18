import { screen } from "@testing-library/react";
import { describe, expect } from "vitest";
import { TaskChatFeed } from "@/components/tasks/TaskChatFeed";
import { NodeLogStatus, TaskSessionEventKind, TaskStatus } from "@/lib/types";
import { makeNodeLog } from "@/test/factories";
import { test } from "@/test/fixtures";
import { renderWithProviders } from "@/test/renderWithProviders";

// jsdom не реализует прокрутку элемента — лента прокручивается к новым записям.
Object.defineProperty(HTMLElement.prototype, "scrollTo", { value: () => {}, configurable: true });

describe("TaskChatFeed", () => {
  test("сброс контекста и новая сессия — репликами между записями нод", async ({ api }) => {
    api.respond("GET /tasks/t1/session-events", [
      { id: "e1", kind: TaskSessionEventKind.SESSION_STARTED, created_at: "2026-01-01T09:00:00Z" },
      { id: "e2", kind: TaskSessionEventKind.CONTEXT_CLEARED, created_at: "2026-01-01T11:00:00Z" },
      { id: "e3", kind: TaskSessionEventKind.SESSION_STARTED, created_at: "2026-01-01T11:00:05Z" },
    ]);
    const logs = [
      makeNodeLog({
        id: "a",
        started_at: "2026-01-01T10:00:00Z",
        status: NodeLogStatus.SUCCESS,
        llm_output_text: "Первый ответ",
      }),
      makeNodeLog({
        id: "b",
        started_at: "2026-01-01T12:00:00Z",
        status: NodeLogStatus.SUCCESS,
        llm_output_text: "Второй ответ",
      }),
    ];

    const { container } = renderWithProviders(
      <TaskChatFeed
        taskId="t1"
        taskStatus={TaskStatus.IN_PROGRESS}
        ownerId="u1"
        nodeLogs={logs}
        header={null}
      />,
    );

    await screen.findAllByText("Начата новая сессия по задаче");
    const text = container.textContent ?? "";
    const positions = [
      text.indexOf("Начата новая сессия по задаче"),
      text.indexOf("Первый ответ"),
      text.indexOf("Контекст задачи сброшен"),
      text.lastIndexOf("Начата новая сессия по задаче"),
      text.indexOf("Второй ответ"),
    ];
    expect(positions).toEqual([...positions].sort((a, b) => a - b));
    expect(positions.every((position) => position >= 0)).toBe(true);
    expect(screen.getAllByRole("note")).toHaveLength(3);
  });

  test("при смене даты в ленте строка с датой", async ({ api }) => {
    api.respond("GET /tasks/t1/session-events", []);
    const logs = [
      makeNodeLog({ id: "a", started_at: new Date(2026, 9, 31, 22, 0).toISOString(), llm_output_text: "Вчера" }),
      makeNodeLog({ id: "b", started_at: new Date(2026, 10, 1, 8, 0).toISOString(), llm_output_text: "Сегодня" }),
    ];

    renderWithProviders(
      <TaskChatFeed
        taskId="t1"
        taskStatus={TaskStatus.IN_PROGRESS}
        ownerId="u1"
        nodeLogs={logs}
        header={null}
      />,
    );

    const separators = await screen.findAllByRole("separator");
    expect(separators.map((item) => item.textContent)).toEqual([
      expect.stringMatching(/31 октября/),
      expect.stringMatching(/1 ноября/),
    ]);
  });

  test("без записей и событий — пустая лента", () => {
    renderWithProviders(
      <TaskChatFeed
        taskId="t1"
        taskStatus={TaskStatus.NEW}
        ownerId="u1"
        nodeLogs={[]}
        header={null}
      />,
    );

    expect(screen.getByText("Задача ещё не запускалась")).toBeInTheDocument();
  });
});
