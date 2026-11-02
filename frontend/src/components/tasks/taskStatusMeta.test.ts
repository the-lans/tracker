import { describe, expect, test } from "vitest";
import { bridgeViewOf } from "@/components/tasks/taskStatusMeta";
import { RemoteControlStatus, TaskStatus } from "@/lib/types";
import { makeTask } from "@/test/factories";

describe("bridgeViewOf", () => {
  test.for([
    { status: TaskStatus.IN_PROGRESS, bridge: RemoteControlStatus.DISCONNECTED, llm: "acc1", view: "reconnect" },
    { status: TaskStatus.PAUSED, bridge: RemoteControlStatus.CONNECTED, llm: "acc1", view: "reconnect" },
    { status: TaskStatus.IN_PROGRESS, bridge: RemoteControlStatus.UNAVAILABLE, llm: "acc1", view: "unavailable" },
    { status: TaskStatus.IN_PROGRESS, bridge: RemoteControlStatus.UNAVAILABLE, llm: null, view: "hidden" },
    { status: TaskStatus.DONE, bridge: RemoteControlStatus.DISCONNECTED, llm: "acc1", view: "hidden" },
  ])("$status, мост $bridge, аккаунт $llm → $view", ({ status, bridge, llm, view }) => {
    expect(
      bridgeViewOf(makeTask({ status, remote_control_status: bridge, llm_account_id: llm })),
    ).toBe(view);
  });
});
