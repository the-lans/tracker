import { render, screen } from "@testing-library/react";
import { describe, expect, test } from "vitest";
import { TaskLimitWaitBanner } from "@/components/tasks/TaskLimitWaitBanner";
import { TaskStatus } from "@/lib/types";
import { makeTask } from "@/test/factories";
import { formatResetTime } from "@/lib/utils";

const UNTIL = "2026-11-10T18:40:00Z";

describe("TaskLimitWaitBanner", () => {
  test.for([
    {
      from: TaskStatus.IN_PROGRESS,
      until: UNTIL,
      text: `Все LLM-аккаунты на пороге — задача продолжит в ${formatResetTime(UNTIL)}`,
    },
    {
      from: TaskStatus.PAUSED,
      until: UNTIL,
      text: `Все LLM-аккаунты на пороге — задача продолжит в ${formatResetTime(UNTIL)}После сброса задача встанет на паузу`,
    },
    {
      from: TaskStatus.REFINING,
      until: null,
      text: "Все LLM-аккаунты на пороге — задача продолжит после сброса лимита",
    },
  ])("ждёт из $from до $until", ({ from, until, text }) => {
    render(
      <TaskLimitWaitBanner
        task={makeTask({ status: TaskStatus.AWAITING_LIMIT, limit_wait_from_status: from, limit_wait_until: until })}
      />,
    );

    expect(screen.getByRole("status").textContent).toBe(text);
  });

  test("без ожидания плашки нет", () => {
    render(<TaskLimitWaitBanner task={makeTask({ status: TaskStatus.IN_PROGRESS, limit_wait_until: UNTIL })} />);

    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });
});
