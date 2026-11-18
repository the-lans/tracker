import { describe, expect, test } from "vitest";
import { mergeFeed } from "@/lib/chatFeed";
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

    const items = mergeFeed([makeNodeLog({ id: "clear", started_at: at })], [event("e", at)]);

    expect(order(items)).toEqual(["clear", "e"]);
  });

  test("запись без времени начала — в конце, порядок записей сохраняется", () => {
    const logs = [
      makeNodeLog({ id: "queued", started_at: null }),
      makeNodeLog({ id: "later", started_at: null }),
      makeNodeLog({ id: "first", started_at: "2026-01-01T10:00:00Z" }),
    ];

    expect(order(mergeFeed(logs, [event("e", "2026-01-01T11:00:00Z")]))).toEqual([
      "first",
      "e",
      "queued",
      "later",
    ]);
  });

  test("без событий лента — записи как есть", () => {
    const logs = [makeNodeLog({ id: "a" }), makeNodeLog({ id: "b" })];

    expect(order(mergeFeed(logs, []))).toEqual(["a", "b"]);
  });
});
