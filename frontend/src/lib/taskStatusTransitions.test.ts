import { describe, expect, test } from "vitest";
import { manualStatusTargets, PRE_LAUNCH_STATUSES } from "@/lib/taskStatusTransitions";
import { TaskStatus } from "@/lib/types";
import { makeTask } from "@/test/factories";

const others = (status: TaskStatus) => PRE_LAUNCH_STATUSES.filter((target) => target !== status);

describe("manualStatusTargets", () => {
  test.for([...PRE_LAUNCH_STATUSES, TaskStatus.FAILED, TaskStatus.DONE])(
    "%s → остальные статусы до запуска",
    (status) => {
      expect(manualStatusTargets(makeTask({ status }))).toEqual(others(status));
    },
  );

  test.for([
    TaskStatus.QUEUED,
    TaskStatus.IN_PROGRESS,
    TaskStatus.PAUSED,
    TaskStatus.PLAN_REVIEW,
    TaskStatus.AWAITING_INPUT,
    TaskStatus.REBASE_CONFLICT,
  ])("%s меняет только система", (status) => {
    expect(manualStatusTargets(makeTask({ status }))).toEqual([]);
  });

  test("пока агент отвечает в чате, статус не меняется", () => {
    expect(manualStatusTargets(makeTask({ status: TaskStatus.REFINING, chat_active: true }))).toEqual([]);
  });
});
