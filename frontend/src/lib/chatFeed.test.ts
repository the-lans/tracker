import { describe, expect, test } from "vitest";
import { mergeFeed, withDateSeparators } from "@/lib/chatFeed";
import { TaskSessionEventKind, type TaskSessionEvent } from "@/lib/types";
import { makeNodeLog } from "@/test/factories";

const event = (id: string, created_at: string): TaskSessionEvent => ({
  id,
  kind: TaskSessionEventKind.SESSION_STARTED,
  created_at,
});

const order = (items: ReturnType<typeof mergeFeed>) =>
  items.map((item) => (item.type === "log" ? item.log.id : item.event.id));

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
