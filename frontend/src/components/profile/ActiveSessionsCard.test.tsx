import { screen } from "@testing-library/react";
import { describe, expect } from "vitest";
import { ActiveSessionsCard } from "@/components/profile/ActiveSessionsCard";
import { RemoteControlStatus, TaskStatus } from "@/lib/types";
import { makeTask } from "@/test/factories";
import { test } from "@/test/fixtures";
import { renderWithProviders } from "@/test/renderWithProviders";

describe("ActiveSessionsCard", () => {
  test("недоступный мост не подписывается, остальные состояния — подписаны", async ({ api }) => {
    api.respond("GET /tasks/active-sessions", [
      makeTask({ id: "a", code: "RR-1", status: TaskStatus.IN_PROGRESS, remote_control_status: RemoteControlStatus.UNAVAILABLE }),
      makeTask({ id: "b", code: "RR-2", status: TaskStatus.IN_PROGRESS, remote_control_status: RemoteControlStatus.CONNECTED }),
      makeTask({ id: "c", code: "RR-3", status: TaskStatus.IN_PROGRESS, llm_account_id: null, current_llm_account_id: null }),
    ]);
    renderWithProviders(<ActiveSessionsCard />);

    expect(await screen.findByText("RR-1")).toBeInTheDocument();
    expect(screen.queryByText("Просмотр в claude.ai/code недоступен")).not.toBeInTheDocument();
    expect(screen.getByText("мост подключён")).toBeInTheDocument();
    expect(screen.getByText("без моста — задача без LLM")).toBeInTheDocument();
  });
});
