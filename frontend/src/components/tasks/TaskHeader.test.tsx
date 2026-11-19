import { screen } from "@testing-library/react";
import { describe, expect } from "vitest";
import { TaskHeader } from "@/components/tasks/TaskHeader";
import { RemoteControlStatus, TaskStatus, type Task } from "@/lib/types";
import { makeTask } from "@/test/factories";
import { test } from "@/test/fixtures";
import { renderWithProviders } from "@/test/renderWithProviders";

const NOTE = "Просмотр в claude.ai/code недоступен";

/** Надпись, видимая пользователю: скрытый замерочный `span` шапки не считается. */
function visibleNotes(): HTMLElement[] {
  return screen
    .queryAllByText(NOTE)
    .filter((element) => element.closest("[aria-hidden]") === null);
}

function renderHeader(overrides: Partial<Task> = {}) {
  return renderWithProviders(
    <TaskHeader task={makeTask({ title: "Моя задача", ...overrides })} />,
  );
}

describe("TaskHeader", () => {
  test("показывает код, название и кнопки управления выполнением", () => {
    renderHeader({ code: "RR-77", status: TaskStatus.IN_PROGRESS });

    expect(screen.getByText("RR-77")).toBeInTheDocument();
    expect(screen.getByText("Моя задача")).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "К списку задач" }),
    ).toHaveAttribute("href", "/");
    expect(
      screen.getByRole("button", { name: "Приостановить" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Остановить" }),
    ).toBeInTheDocument();
  });

  test("мост недоступен — надпись про claude.ai/code, кнопки переподключения нет", () => {
    renderHeader({
      status: TaskStatus.IN_PROGRESS,
      remote_control_status: RemoteControlStatus.UNAVAILABLE,
    });

    expect(visibleNotes().length).toBeGreaterThan(0);
    expect(
      screen.queryByRole("button", { name: /Переподключить/ }),
    ).not.toBeInTheDocument();
  });

  test("мост подключён — надписи нет", () => {
    renderHeader({
      status: TaskStatus.IN_PROGRESS,
      remote_control_status: RemoteControlStatus.CONNECTED,
    });

    expect(visibleNotes()).toHaveLength(0);
  });

  test("в статусе до запуска вместо остановки — «Запустить»", () => {
    renderHeader({ status: TaskStatus.NEW });

    expect(
      screen.getByRole("button", { name: "Запустить задачу" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Остановить" }),
    ).not.toBeInTheDocument();
  });
});
