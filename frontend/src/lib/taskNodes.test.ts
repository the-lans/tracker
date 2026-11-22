import { describe, expect, it } from "vitest";
import { insertOrderIndex, isPositionEditable } from "@/lib/taskNodes";
import { TaskStatus } from "@/lib/types";
import { makeTask, makeTaskNode } from "@/test/factories";

const node = (order_index: number, editable = true) =>
  makeTaskNode({ id: `tn${order_index}`, order_index, editable });

describe("isPositionEditable", () => {
  it.each([TaskStatus.NEW, TaskStatus.REFINING, TaskStatus.DEFINED, TaskStatus.READY])(
    "до запуска (%s) — любая позиция",
    (status) => {
      expect(isPositionEditable(makeTask({ status }), [node(0, false)], 0)).toBe(true);
    },
  );

  it.each([
    TaskStatus.IN_PROGRESS,
    TaskStatus.PAUSED,
    TaskStatus.PLAN_REVIEW,
    TaskStatus.AWAITING_INPUT,
    TaskStatus.REBASE_CONFLICT,
    TaskStatus.AWAITING_LIMIT,
  ])("%s: только за границей начатых нод", (status) => {
    const task = makeTask({ status });
    const nodes = [node(0, false), node(1, false), node(2), node(3)];

    expect([0, 1, 2, 3, 4].map((index) => isPositionEditable(task, nodes, index))).toEqual([
      false,
      false,
      true,
      true,
      true,
    ]);
  });

  it("у задачи в работе без начатых нод открыто всё", () => {
    const task = makeTask({ status: TaskStatus.IN_PROGRESS });

    expect(isPositionEditable(task, [node(0), node(1)], 0)).toBe(true);
  });

  it.each([TaskStatus.QUEUED, TaskStatus.DONE, TaskStatus.ARCHIVED])(
    "%s: состав заблокирован",
    (status) => {
      expect(isPositionEditable(makeTask({ status }), [node(0)], 5)).toBe(false);
    },
  );

  it("в failed — за точкой перезапуска", () => {
    const task = makeTask({ status: TaskStatus.FAILED, last_failed_order_index: 1 });

    expect(isPositionEditable(task, [node(0, false), node(1, false), node(2)], 2)).toBe(true);
    expect(isPositionEditable(task, [node(0, false), node(1, false), node(2)], 1)).toBe(false);
  });
});

describe("insertOrderIndex", () => {
  it("сразу после ноды или в начале снимка", () => {
    expect(insertOrderIndex([node(2), node(3)], node(2))).toBe(3);
    expect(insertOrderIndex([node(2), node(3)], null)).toBe(2);
    expect(insertOrderIndex([], null)).toBe(0);
  });
});
