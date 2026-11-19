import { render, screen } from "@testing-library/react";
import { describe, expect, test } from "vitest";
import { SessionEventNotice } from "@/components/tasks/SessionEventNotice";
import { TaskSessionEventKind } from "@/lib/types";

describe("SessionEventNotice", () => {
  test.each([
    [TaskSessionEventKind.CONTEXT_CLEARED, "Контекст задачи сброшен"],
    [TaskSessionEventKind.SESSION_STARTED, "Начата новая сессия по задаче"],
  ])("%s → «%s»", (kind, text) => {
    render(<SessionEventNotice kind={kind} />);

    expect(screen.getByRole("note")).toHaveTextContent(text);
  });
});
