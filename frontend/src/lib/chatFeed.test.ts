import { describe, expect, test } from "vitest";
import { mergeFeed, splitInjected, withDateSeparators } from "@/lib/chatFeed";
import {
  NodeLogStatus,
  NodeLogTriggerType,
  TaskSessionEventKind,
  type TaskSessionEvent,
} from "@/lib/types";
import { makeNodeLog } from "@/test/factories";

const event = (id: string, created_at: string): TaskSessionEvent => ({
  id,
  kind: TaskSessionEventKind.SESSION_STARTED,
  created_at,
});

const order = (items: ReturnType<typeof mergeFeed>) =>
  items.map((item) => (item.type === "log" ? item.log.id : item.event.id));

const injected = (id: string, at: string) =>
  makeNodeLog({
    id,
    node_id: null,
    trigger_type: NodeLogTriggerType.FREEFORM_MANUAL,
    rendered_prompt: "влитое сообщение",
    started_at: at,
    finished_at: at,
  });

describe("splitInjected", () => {
  const turn = (overrides = {}) =>
    makeNodeLog({
      id: "turn",
      started_at: "2026-01-01T10:00:00Z",
      finished_at: null,
      status: NodeLogStatus.RUNNING,
      ...overrides,
    });
  const ids = (logs: ReturnType<typeof makeNodeLog>[]) => logs.map((log) => log.id);

  test("влитый промт уходит в идущий ход и пропадает из ленты", () => {
    const { logs, injectedBy } = splitInjected([turn(), injected("inj", "2026-01-01T10:05:00Z")]);

    expect(ids(logs)).toEqual(["turn"]);
    expect(ids(injectedBy.get("turn") ?? [])).toEqual(["inj"]);
  });

  test("после завершения хода остаётся в нём", () => {
    const { logs, injectedBy } = splitInjected([
      turn({ finished_at: "2026-01-01T10:20:00Z", status: NodeLogStatus.SUCCESS }),
      injected("inj", "2026-01-01T10:05:00Z"),
    ]);

    expect(ids(logs)).toEqual(["turn"]);
    expect(ids(injectedBy.get("turn") ?? [])).toEqual(["inj"]);
  });

  test("несколько влитых — в порядке взятия", () => {
    const { injectedBy } = splitInjected([
      turn(),
      injected("second", "2026-01-01T10:09:00Z"),
      injected("first", "2026-01-01T10:05:00Z"),
    ]);

    expect(ids(injectedBy.get("turn") ?? [])).toEqual(["first", "second"]);
  });

  test("запись, не попавшая в ход, остаётся в ленте по времени", () => {
    const { logs, injectedBy } = splitInjected([
      turn({ finished_at: "2026-01-01T10:20:00Z" }),
      injected("later", "2026-01-01T11:00:00Z"),
    ]);

    expect(ids(logs)).toEqual(["turn", "later"]);
    expect(injectedBy.size).toBe(0);
  });

  test("обычный ручной промт с ответом не считается влитым", () => {
    const manual = makeNodeLog({
      id: "manual",
      trigger_type: NodeLogTriggerType.FREEFORM_MANUAL,
      rendered_prompt: "вопрос",
      llm_output_text: "ответ",
      started_at: "2026-01-01T10:05:00Z",
      finished_at: "2026-01-01T10:06:00Z",
    });

    const { logs, injectedBy } = splitInjected([turn({ finished_at: "2026-01-01T10:20:00Z" }), manual]);

    expect(ids(logs)).toEqual(["turn", "manual"]);
    expect(injectedBy.size).toBe(0);
  });

  test("скрипт ходом модели не считается", () => {
    const script = makeNodeLog({
      id: "script",
      started_at: "2026-01-01T10:00:00Z",
      finished_at: "2026-01-01T10:20:00Z",
      script_stdout: "ok",
      script_exit_code: 0,
    });

    const { logs } = splitInjected([script, injected("inj", "2026-01-01T10:05:00Z")]);

    expect(ids(logs)).toEqual(["script", "inj"]);
  });
});

describe("mergeFeed", () => {
  test("события стоят между записями нод по времени", () => {
    const logs = [
      makeNodeLog({ id: "a", started_at: "2026-01-01T10:00:00Z" }),
      makeNodeLog({ id: "b", started_at: "2026-01-01T12:00:00Z" }),
    ];

    const items = mergeFeed(logs, [
      event("late", "2026-01-01T13:00:00Z"),
      event("early", "2026-01-01T09:00:00Z"),
      event("middle", "2026-01-01T11:00:00Z"),
    ]);

    expect(order(items)).toEqual(["early", "a", "middle", "b", "late"]);
  });

  test("при равном времени запись ноды раньше события", () => {
    const at = "2026-01-01T10:00:00Z";

    const items = mergeFeed(
      [makeNodeLog({ id: "clear", started_at: at })],
      [event("e", at)],
    );

    expect(order(items)).toEqual(["clear", "e"]);
  });

  test("запись без времени начала — в конце, порядок записей сохраняется", () => {
    const logs = [
      makeNodeLog({ id: "queued", started_at: null }),
      makeNodeLog({ id: "later", started_at: null }),
      makeNodeLog({ id: "first", started_at: "2026-01-01T10:00:00Z" }),
    ];

    expect(
      order(mergeFeed(logs, [event("e", "2026-01-01T11:00:00Z")])),
    ).toEqual(["first", "e", "queued", "later"]);
  });

  test("без событий лента — записи как есть", () => {
    const logs = [makeNodeLog({ id: "a" }), makeNodeLog({ id: "b" })];

    expect(order(mergeFeed(logs, []))).toEqual(["a", "b"]);
  });
});

describe("withDateSeparators", () => {
  const local = (day: number, hours: number) =>
    new Date(2026, 10, day, hours, 0).toISOString();
  const kinds = (
    logs: ReturnType<typeof makeNodeLog>[],
    events: TaskSessionEvent[] = [],
  ) =>
    withDateSeparators(mergeFeed(logs, events)).map((entry) =>
      entry.type === "date"
        ? "date"
        : entry.type === "log"
          ? entry.log.id
          : entry.event.id,
    );

  test("дата стоит перед первой записью и при смене дня", () => {
    const logs = [
      makeNodeLog({ id: "a", started_at: local(10, 9) }),
      makeNodeLog({ id: "b", started_at: local(10, 18) }),
      makeNodeLog({ id: "c", started_at: local(11, 8) }),
    ];

    expect(kinds(logs)).toEqual(["date", "a", "b", "date", "c"]);
  });

  test("событие сессии тоже может открыть новый день", () => {
    const logs = [makeNodeLog({ id: "a", started_at: local(10, 22) })];

    expect(kinds(logs, [event("e", local(11, 1))])).toEqual([
      "date",
      "a",
      "date",
      "e",
    ]);
  });

  test("запись без времени начала даты не добавляет и не прерывает день", () => {
    const logs = [
      makeNodeLog({ id: "a", started_at: local(10, 9) }),
      makeNodeLog({ id: "queued", started_at: null }),
    ];

    expect(kinds(logs)).toEqual(["date", "a", "queued"]);
  });

  test("дата всегда перед блоком: в конце ленты и подряд двух дат не бывает", () => {
    const logs = [
      makeNodeLog({ id: "a", started_at: local(9, 9) }),
      makeNodeLog({ id: "b", started_at: local(11, 9) }),
      makeNodeLog({ id: "c", started_at: local(15, 9) }),
      makeNodeLog({ id: "queued", started_at: null }),
    ];

    const entries = kinds(logs);

    expect(entries[entries.length - 1]).not.toBe("date");
    entries.slice(1).forEach((entry, index) => {
      if (entries[index] === "date") expect(entry).not.toBe("date");
    });
    expect(entries.filter((entry) => entry === "date")).toHaveLength(3);
  });

  test("пустая лента — без дат", () => {
    expect(kinds([])).toEqual([]);
  });
});
