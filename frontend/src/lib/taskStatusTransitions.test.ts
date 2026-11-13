import { describe, expect, test } from "vitest";
import {
  isDuplicable,
  isFinished,
  isReadOnly,
  manualStatusTargets,
  PRE_LAUNCH_STATUSES,
} from "@/lib/taskStatusTransitions";
import { TaskStatus } from "@/lib/types";
import { makeTask } from "@/test/factories";

const others = (status: TaskStatus) => PRE_LAUNCH_STATUSES.filter((target) => target !== status);

describe("manualStatusTargets", () => {
  test.for([...PRE_LAUNCH_STATUSES, TaskStatus.FAILED, TaskStatus.DONE, TaskStatus.ARCHIVED])(
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

describe("завершённая задача", () => {
  test.for([
    { status: TaskStatus.DONE, finished: true, readOnly: true },
    { status: TaskStatus.FAILED, finished: true, readOnly: false },
    { status: TaskStatus.ARCHIVED, finished: true, readOnly: true },
    { status: TaskStatus.IN_PROGRESS, finished: false, readOnly: false },
    { status: TaskStatus.NEW, finished: false, readOnly: false },
  ])("$status: завершена — $finished, только чтение — $readOnly", ({ status, finished, readOnly }) => {
    expect(isFinished(status)).toBe(finished);
    expect(isReadOnly(status)).toBe(readOnly);
  });

  test.for([
    { status: TaskStatus.DONE, from: null, duplicable: true },
    { status: TaskStatus.ARCHIVED, from: TaskStatus.DONE, duplicable: true },
    { status: TaskStatus.ARCHIVED, from: TaskStatus.FAILED, duplicable: false },
    { status: TaskStatus.FAILED, from: null, duplicable: false },
  ])("$status из $from — дублируется: $duplicable", ({ status, from, duplicable }) => {
    expect(isDuplicable(makeTask({ status, archived_from_status: from }))).toBe(duplicable);
  });
});
