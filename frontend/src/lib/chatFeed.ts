import type { NodeLog, TaskSessionEvent } from "@/lib/types";

/** Элемент ленты чата: запись ноды или событие сессии (раздел 15.2). */
export type FeedItem =
  | { type: "log"; log: NodeLog; at: number }
  | { type: "event"; event: TaskSessionEvent; at: number };

/** Строка ленты: элемент или дата, с которой начинается новый день. */
export type FeedEntry = FeedItem | { type: "date"; at: number };

// Запись без времени начала (ещё не стартовала) стоит в конце ленты.
const NO_TIME = Number.MAX_SAFE_INTEGER;

/**
 * События сессии — между записями нод по времени. При равном времени запись
 * ноды идёт раньше события: сброс контекста пишется вместе с записью ноды
 * `clear_context` и должен стоять под её заголовком. Порядок записей нод
 * сохраняется, как его отдал сервер.
 */
export function mergeFeed(logs: NodeLog[], events: TaskSessionEvent[]): FeedItem[] {
  const items: FeedItem[] = [
    ...logs.map((log): FeedItem => ({
      type: "log",
      log,
      at: log.started_at ? Date.parse(log.started_at) : NO_TIME,
    })),
    ...events.map((event): FeedItem => ({
      type: "event",
      event,
      at: Date.parse(event.created_at),
    })),
  ];
  return items
    .map((item, index) => ({ item, index }))
    .sort((a, b) => a.item.at - b.item.at || rank(a.item) - rank(b.item) || a.index - b.index)
    .map(({ item }) => item);
}

const rank = (item: FeedItem): number => (item.type === "log" ? 0 : 1);

/** Календарный день по местному времени — ключ смены даты. */
function dayKey(at: number): string {
  const date = new Date(at);
  return `${date.getFullYear()}-${date.getMonth()}-${date.getDate()}`;
}

/**
 * Раздел 15.2: перед первым элементом и при каждой смене календарного дня в
 * ленте стоит строка с датой. Запись без времени начала (ещё не стартовала)
 * даты не открывает и не меняет.
 */
export function withDateSeparators(items: FeedItem[]): FeedEntry[] {
  const entries: FeedEntry[] = [];
  let previousDay: string | null = null;
  for (const item of items) {
    if (item.at !== NO_TIME) {
      const day = dayKey(item.at);
      if (day !== previousDay) entries.push({ type: "date", at: item.at });
      previousDay = day;
    }
    entries.push(item);
  }
  return entries;
}
