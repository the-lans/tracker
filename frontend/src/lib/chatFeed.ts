import { NodeLogStatus, NodeLogTriggerType, type NodeLog, type TaskSessionEvent } from "@/lib/types";

/** Элемент ленты чата: запись ноды или событие сессии (раздел 15.2). */
export type FeedItem =
  | { type: "log"; log: NodeLog; at: number }
  | { type: "event"; event: TaskSessionEvent; at: number };

/** Строка ленты: элемент или дата, с которой начинается новый день. */
export type FeedEntry = FeedItem | { type: "date"; at: number };

// Запись без времени начала (ещё не стартовала) стоит в конце ленты.
const NO_TIME = Number.MAX_SAFE_INTEGER;

const isScriptLog = (log: NodeLog): boolean =>
  log.script_stdout !== null || log.script_exit_code !== null;

/**
 * Влитый в идущий ход промт (раздел 7.3): запись «Отправлено вручную» без ответа,
 * начатая и законченная в один момент — момент, когда агент взял сообщение.
 */
export function isInjectedPrompt(log: NodeLog): boolean {
  return (
    log.trigger_type === NodeLogTriggerType.FREEFORM_MANUAL &&
    log.status === NodeLogStatus.SUCCESS &&
    Boolean(log.rendered_prompt) &&
    log.llm_output_text === null &&
    log.started_at !== null &&
    log.started_at === log.finished_at
  );
}

/**
 * Ход модели, в который влит промт: начатый не позже и ещё не завершённый (или
 * завершённый не раньше) момента взятия. Из нескольких — последний начатый.
 */
function hostTurnOf(injected: NodeLog, logs: NodeLog[]): NodeLog | undefined {
  const takenAt = Date.parse(injected.started_at ?? "");
  let host: NodeLog | undefined;
  for (const log of logs) {
    if (log === injected || isInjectedPrompt(log) || isScriptLog(log) || !log.started_at) continue;
    const startedAt = Date.parse(log.started_at);
    const finishedAt = log.finished_at ? Date.parse(log.finished_at) : Infinity;
    if (startedAt > takenAt || finishedAt < takenAt) continue;
    if (!host || startedAt >= Date.parse(host.started_at ?? "")) host = log;
  }
  return host;
}

/** Записи ленты без влитых промтов и влитые промты по записи хода, в который они влиты. */
export interface SplitLogs {
  logs: NodeLog[];
  injectedBy: Map<string, NodeLog[]>;
}

/**
 * Влитый промт показывается внутри записи хода — между промтом ноды и ответом
 * модели, — а не отдельной записью после неё: ответ модели остаётся последним
 * внизу. Влитые — в порядке взятия агентом. Запись, не попавшая ни в один ход,
 * остаётся в ленте по времени.
 */
export function splitInjected(logs: NodeLog[]): SplitLogs {
  const injectedBy = new Map<string, NodeLog[]>();
  const attached = new Set<NodeLog>();
  for (const log of logs) {
    if (!isInjectedPrompt(log)) continue;
    const host = hostTurnOf(log, logs);
    if (!host) continue;
    attached.add(log);
    injectedBy.set(host.id, [...(injectedBy.get(host.id) ?? []), log]);
  }
  for (const group of injectedBy.values()) {
    group.sort((a, b) => Date.parse(a.started_at ?? "") - Date.parse(b.started_at ?? ""));
  }
  return { logs: logs.filter((log) => !attached.has(log)), injectedBy };
}

/**
 * События сессии — между записями нод по времени. При равном времени запись
 * ноды идёт раньше события: сброс контекста пишется вместе с записью ноды
 * `clear_context` и должен стоять под её заголовком. Порядок записей нод
 * сохраняется, как его отдал сервер.
 */
export function mergeFeed(
  logs: NodeLog[],
  events: TaskSessionEvent[],
): FeedItem[] {
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
    .sort(
      (a, b) =>
        a.item.at - b.item.at ||
        rank(a.item) - rank(b.item) ||
        a.index - b.index,
    )
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
