import { act, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, vi } from "vitest";
import { BRIDGE_RECONNECT_POLL_MS, useTask } from "@/hooks/useTasks";
import { RemoteControlStatus } from "@/lib/types";
import { makeTask } from "@/test/factories";
import { test } from "@/test/fixtures";
import { renderHookWithClient } from "@/test/renderWithProviders";

describe("useTask", () => {
  beforeEach(() => vi.useFakeTimers({ shouldAdvanceTime: true }));
  afterEach(() => vi.useRealTimers());

  test("пока мост переподключается, карточка перечитывается до итога воркера", async ({ api }) => {
    const statuses = [RemoteControlStatus.RECONNECTING, RemoteControlStatus.CONNECTED];
    api.respond("GET /tasks/t1", () => makeTask({ id: "t1", remote_control_status: statuses.shift() ?? RemoteControlStatus.CONNECTED }));
    const { result } = renderHookWithClient(() => useTask("t1"));
    await waitFor(() => expect(result.current.data?.remote_control_status).toBe(RemoteControlStatus.RECONNECTING));

    await act(() => vi.advanceTimersByTimeAsync(BRIDGE_RECONNECT_POLL_MS));

    await waitFor(() => expect(result.current.data?.remote_control_status).toBe(RemoteControlStatus.CONNECTED));
  });

  test.for([RemoteControlStatus.CONNECTED, RemoteControlStatus.DISCONNECTED])(
    "мост «%s» — карточка сама не перечитывается",
    async (status, { api }) => {
      api.respond("GET /tasks/t1", () => makeTask({ id: "t1", remote_control_status: status }));
      const { result } = renderHookWithClient(() => useTask("t1"));
      await waitFor(() => expect(result.current.isSuccess).toBe(true));

      await act(() => vi.advanceTimersByTimeAsync(BRIDGE_RECONNECT_POLL_MS * 3));

      expect(api.requests.filter((request) => request.path === "/tasks/t1")).toHaveLength(1);
    },
  );
});
