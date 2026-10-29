import { act } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useTaskOutputStream, useTaskStatusSocket } from "@/hooks/useTaskStatusSocket";
import { TaskStatus, type Task } from "@/lib/types";
import { writeStoredSession } from "@/stores/authContext";
import { FakeWebSocket, stubWebSocket } from "@/test/fakeWebSocket";
import { makeCurrentUser, makeTask } from "@/test/factories";
import { createTestQueryClient, renderHookWithClient } from "@/test/renderWithProviders";

const RECONNECT_DELAY_MS = 3000;

/** Ключи, которые событие статуса обязано перечитать. */
const REFRESHED_KEYS = [
  ["tasks", "list", "all"],
  ["tasks", "t1", "node-logs"],
  ["tasks", "t1", "artifacts"],
  ["tasks", "t1", "repositories"],
  ["tasks", "awaiting-count"],
];

function renderSocket({ withTask = true } = {}) {
  const taskId = withTask ? "t1" : undefined;
  const queryClient = createTestQueryClient();
  queryClient.setQueryData<Task>(["tasks", "detail", "t1"], makeTask({ status: TaskStatus.IN_PROGRESS }));
  for (const key of REFRESHED_KEYS) queryClient.setQueryData(key, []);
  const view = renderHookWithClient(
    ({ id }: { id: string | undefined }) => {
      useTaskStatusSocket(id);
      return useTaskOutputStream("t1");
    },
    { queryClient, initialProps: { id: taskId } },
  );
  return view;
}

/** TanStack Query уведомляет подписчиков через таймер — при подменённых таймерах его нужно прокрутить. */
function flushRender() {
  act(() => vi.advanceTimersByTime(0));
}

describe("useTaskStatusSocket", () => {
  beforeEach(() => {
    stubWebSocket();
    writeStoredSession({ token: "session-token-123", user: makeCurrentUser() });
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
    writeStoredSession(null);
  });

  it("токен уходит первым сообщением, а не в адресе", () => {
    renderSocket();
    const socket = FakeWebSocket.latest();

    socket.open();

    expect(socket.url).toBe(`ws://${window.location.host}/ws/tasks/t1/status`);
    expect(socket.sent.map((message) => JSON.parse(message))).toEqual([
      { type: "auth", token: "session-token-123" },
    ]);
  });

  it("без задачи соединения нет", () => {
    renderSocket({ withTask: false });

    expect(FakeWebSocket.instances).toHaveLength(0);
  });

  it("смена статуса обновляет задачу и перечитывает ленту, списки, артефакты и репозитории", () => {
    const { queryClient } = renderSocket();

    act(() => FakeWebSocket.latest().receive({ type: "status", task_id: "t1", status: TaskStatus.PLAN_REVIEW }));

    expect(queryClient.getQueryData<Task>(["tasks", "detail", "t1"])?.status).toBe(TaskStatus.PLAN_REVIEW);
    for (const key of REFRESHED_KEYS) {
      expect(queryClient.getQueryState(key)?.isInvalidated, key.join("/")).toBe(true);
    }
  });

  it("фрагменты ответа копятся по записи лога и не сбрасываются сменой статуса", () => {
    const { result } = renderSocket();
    const socket = FakeWebSocket.latest();

    act(() => {
      socket.receive({ type: "output_delta", node_log_id: "log1", text: "Добавляю " });
      socket.receive({ type: "output_delta", node_log_id: "log2", text: "Другой ход" });
      socket.receive({ type: "status", task_id: "t1", status: TaskStatus.PAUSED });
      socket.receive({ type: "output_delta", node_log_id: "log1", text: "кнопку" });
    });
    flushRender();

    expect(result.current).toEqual({ log1: "Добавляю кнопку", log2: "Другой ход" });
  });

  it("сообщение не в JSON игнорируется, следующие обрабатываются", () => {
    const { result } = renderSocket();
    const socket = FakeWebSocket.latest();

    act(() => {
      socket.receive("not json");
      socket.receive({ type: "output_delta", node_log_id: "log1", text: "ok" });
    });
    flushRender();

    expect(result.current).toEqual({ log1: "ok" });
  });

  describe("обрыв соединения", () => {
    it("переподключается через паузу и снова авторизуется", () => {
      renderSocket();

      FakeWebSocket.latest().drop(1006);
      vi.advanceTimersByTime(RECONNECT_DELAY_MS - 1);
      expect(FakeWebSocket.instances).toHaveLength(1);
      vi.advanceTimersByTime(1);
      expect(FakeWebSocket.instances).toHaveLength(2);
      FakeWebSocket.latest().open();

      expect(FakeWebSocket.latest().sent).toHaveLength(1);
    });

    it.each([4401, 4404])("код %i — без переподключения", (code) => {
      renderSocket();

      FakeWebSocket.latest().drop(code);
      vi.advanceTimersByTime(RECONNECT_DELAY_MS * 3);

      expect(FakeWebSocket.instances).toHaveLength(1);
    });

    it("уход со страницы закрывает сокет и отменяет переподключение", () => {
      const { unmount } = renderSocket();
      const first = FakeWebSocket.latest();
      first.drop(1006);
      vi.advanceTimersByTime(RECONNECT_DELAY_MS);
      const second = FakeWebSocket.latest();

      unmount();
      vi.advanceTimersByTime(RECONNECT_DELAY_MS * 3);

      expect(second.closed).toBe(true);
      expect(FakeWebSocket.instances).toHaveLength(2);
    });

    it("уход со страницы во время паузы отменяет переподключение", () => {
      const { unmount } = renderSocket();

      FakeWebSocket.latest().drop(1006);
      unmount();
      vi.advanceTimersByTime(RECONNECT_DELAY_MS * 3);

      expect(FakeWebSocket.instances).toHaveLength(1);
    });

    it("смена задачи — новое соединение, старое закрыто", () => {
      const { rerender } = renderSocket();
      const first = FakeWebSocket.latest();

      rerender({ id: "t2" });

      expect(first.closed).toBe(true);
      expect(FakeWebSocket.latest().url).toContain("/ws/tasks/t2/status");
      expect(FakeWebSocket.instances).toHaveLength(2);
    });
  });
});
