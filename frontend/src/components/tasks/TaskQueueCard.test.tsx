import { screen } from "@testing-library/react";
import { describe, expect, vi } from "vitest";
import { TaskQueueCard } from "@/components/tasks/TaskQueueCard";
import { TaskStatus, type Task } from "@/lib/types";
import type { MockedApi } from "@/test/apiMock";
import { makeTask } from "@/test/factories";
import { test } from "@/test/fixtures";
import { renderWithProviders } from "@/test/renderWithProviders";

const SETTINGS = {
  default_timeout_seconds: 900,
  default_max_retries: 2,
  default_retry_base_delay_seconds: 10,
  night_window_start: "03:15:00",
  night_window_end: "07:00:00",
};

function renderCard(api: MockedApi, task: Partial<Task> = {}) {
  api.respond("GET /system-settings", SETTINGS);
  const onUpdate = vi.fn();
  return {
    onUpdate,
    ...renderWithProviders(<TaskQueueCard task={makeTask(task)} pending={false} onUpdate={onUpdate} />),
  };
}

const priority = () => screen.getByRole("spinbutton", { name: "Приоритет" });

describe("TaskQueueCard", () => {
  describe("приоритет", () => {
    test.for([
      { input: "250{Enter}", saved: [{ queue_priority: 250 }] },
      { input: "7", saved: [{ queue_priority: 7 }], blur: true },
      { input: "0{Enter}", saved: [] },
      { input: "1000001{Enter}", saved: [] },
      { input: "1.5{Enter}", saved: [] },
      { input: "100{Enter}", saved: [] },
      { input: "300{Escape}", saved: [] },
    ])("«$input» → $saved", async ({ input, saved, blur }, { api }) => {
      const { user, onUpdate } = renderCard(api);

      await user.clear(priority());
      await user.type(priority(), input);
      if (blur) await user.tab();

      expect(onUpdate.mock.calls.map(([body]) => body)).toEqual(saved);
    });

    test("неверное значение подсвечивается с подсказкой диапазона", async ({ api }) => {
      const { user } = renderCard(api);

      await user.clear(priority());
      await user.type(priority(), "0");

      expect(priority()).toHaveAttribute("aria-invalid", "true");
      expect(screen.getByText("Целое число от 1 до 1 000 000")).toBeInTheDocument();
    });
  });

  test.for([false, true])("галочка слота %s переключается", async (occupies, { api }) => {
    const { user, onUpdate } = renderCard(api, { occupies_slot: occupies });

    await user.click(screen.getByRole("checkbox", { name: "Занимать слот параллельного запуска задач" }));

    expect(onUpdate).toHaveBeenCalledWith({ occupies_slot: !occupies });
  });

  describe("место в очереди", () => {
    test.for([TaskStatus.NEW, TaskStatus.IN_PROGRESS])("%s — не в очереди", (status, { api }) => {
      renderCard(api, { status, queue_position: null });

      expect(screen.queryByText(/^№\d+ в очереди$/)).not.toBeInTheDocument();
    });

    test("ready — номер и время постановки, без ночного окна", async ({ api }) => {
      api.respond("GET /system-settings", SETTINGS);
      // Рядом карточка ночной задачи: её окно показывает, что настройки уже загружены.
      renderWithProviders(
        <>
          <TaskQueueCard
            task={makeTask({ status: TaskStatus.READY, queue_position: 2, ready_at: "2026-11-08T09:30:00Z" })}
            pending={false}
            onUpdate={vi.fn()}
          />
          <TaskQueueCard
            task={makeTask({ id: "t2", status: TaskStatus.NIGHT_WORKER, queue_position: 1 })}
            pending={false}
            onUpdate={vi.fn()}
          />
        </>,
      );

      expect(screen.getByText("№2 в очереди")).toBeInTheDocument();
      expect(screen.getByText(/^В очереди с /)).toBeInTheDocument();
      expect(await screen.findAllByText(/ночном окне/)).toHaveLength(1);
    });

    test("night_worker — ночное окно из настроек", async ({ api }) => {
      renderCard(api, { status: TaskStatus.NIGHT_WORKER, queue_position: 1 });

      expect(await screen.findByText("Запустится в ночном окне 03:15–07:00 МСК")).toBeInTheDocument();
    });
  });
});
