import { act, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, vi } from "vitest";
import {
  STOP_TASK_ARMING_MS,
  TaskStopButton,
} from "@/components/tasks/TaskStopButton";
import { ManualRequestStatus, ManualRequestType } from "@/lib/types";
import { makeManualRequest } from "@/test/factories";
import { test } from "@/test/fixtures";
import { renderWithProviders } from "@/test/renderWithProviders";

const RUNNING = makeManualRequest({
  id: "mq1",
  status: ManualRequestStatus.PROCESSING,
});
const QUEUED_COMMAND = makeManualRequest({
  id: "mq2",
  command_name: "review",
  command_revision: 2,
  request_type: ManualRequestType.LIBRARY_PROMPT,
});

function renderButton() {
  return renderWithProviders(<TaskStopButton taskId="t1" />);
}

const isDanger = (button: HTMLElement) =>
  button.className.includes("bg-danger-tint");

describe("TaskStopButton", () => {
  test("без запросов — красная кнопка завершает задачу после подтверждения", async ({
    api,
  }) => {
    const { user } = renderButton();

    const button = await screen.findByRole("button", { name: "Остановить" });
    expect(isDanger(button)).toBe(true);
    expect(button).toHaveAttribute("title", "Остановить задачу целиком");
    await user.click(button);
    await user.click(
      within(await screen.findByRole("dialog")).getByRole("button", {
        name: "Остановить",
      }),
    );

    expect(api.mutations().map((request) => request.path)).toEqual([
      "/tasks/t1/stop",
    ]);
  });

  test("выполняющийся промт — обычная кнопка останавливает только его", async ({
    api,
  }) => {
    api.respond("GET /tasks/t1/manual-queue", [RUNNING]);
    const { user } = renderButton();

    const button = await screen.findByRole("button", {
      name: "Остановить промт",
    });
    expect(isDanger(button)).toBe(false);
    await user.click(button);

    expect(api.mutations().map((request) => request.path)).toEqual([
      "/tasks/t1/manual-queue/mq1/stop",
    ]);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  test("ожидающая команда — «Отменить /команда»", async ({ api }) => {
    api.respond("GET /tasks/t1/manual-queue", [QUEUED_COMMAND]);
    renderButton();

    expect(
      await screen.findByRole("button", { name: "Отменить /review" }),
    ).toBeInTheDocument();
  });

  test("ожидающий свободный промт кнопки не меняет", async ({ api }) => {
    api.respond("GET /tasks/t1/manual-queue", [makeManualRequest()]);
    renderButton();

    expect(
      isDanger(await screen.findByRole("button", { name: "Остановить" })),
    ).toBe(true);
  });

  test("ошибка остановки запроса показывается пользователю", async ({
    api,
    toasts,
  }) => {
    api.respond("GET /tasks/t1/manual-queue", [RUNNING]);
    api.respond("POST /tasks/t1/manual-queue/mq1/stop", {
      error: { status: 409, message: "Запрос уже завершён" },
    });
    const { user } = renderButton();

    await user.click(
      await screen.findByRole("button", { name: "Остановить промт" }),
    );

    await expect
      .poll(() => toasts.error)
      .toHaveBeenCalledWith("Запрос уже завершён");
  });

  describe("по одному и пауза", () => {
    beforeEach(() => vi.useFakeTimers({ shouldAdvanceTime: true }));
    afterEach(() => vi.useRealTimers());

    test("сначала выполняющийся, затем очередь, потом красная кнопка с паузой", async ({
      api,
    }) => {
      api.respond("GET /tasks/t1/manual-queue", [QUEUED_COMMAND, RUNNING]);
      const { user } = renderButton();

      await user.click(
        await screen.findByRole("button", { name: "Остановить промт" }),
      );
      // Остановленный запрос ещё в списке, но второй раз его не останавливают.
      await user.click(
        await screen.findByRole("button", { name: "Отменить /review" }),
      );
      expect(api.mutations().map((request) => request.path)).toEqual([
        "/tasks/t1/manual-queue/mq1/stop",
        "/tasks/t1/manual-queue/mq2/stop",
      ]);

      const red = await screen.findByRole("button", { name: "Остановить" });
      expect(isDanger(red)).toBe(true);
      expect(red).toBeDisabled();
      await act(async () => {
        await vi.advanceTimersByTimeAsync(STOP_TASK_ARMING_MS + 50);
      });
      expect(screen.getByRole("button", { name: "Остановить" })).toBeEnabled();
    });
  });
});
