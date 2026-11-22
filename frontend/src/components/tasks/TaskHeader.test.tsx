import { screen } from "@testing-library/react";
import { describe, expect } from "vitest";
import { TaskHeader } from "@/components/tasks/TaskHeader";
import { RemoteControlStatus, TaskStatus, type Task } from "@/lib/types";
import { makeTask } from "@/test/factories";
import { test } from "@/test/fixtures";
import { renderWithProviders } from "@/test/renderWithProviders";

const NOTE = "Просмотр в claude.ai/code недоступен";

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

  test("мост недоступен — ни надписи про claude.ai/code, ни кнопки переподключения", () => {
    renderHeader({
      status: TaskStatus.IN_PROGRESS,
      remote_control_status: RemoteControlStatus.UNAVAILABLE,
    });

    expect(screen.queryByText(NOTE)).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Переподключить/ }),
    ).not.toBeInTheDocument();
  });

  test("мост подключён — надписи тоже нет", () => {
    renderHeader({
      status: TaskStatus.IN_PROGRESS,
      remote_control_status: RemoteControlStatus.CONNECTED,
    });

    expect(screen.queryByText(NOTE)).not.toBeInTheDocument();
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
