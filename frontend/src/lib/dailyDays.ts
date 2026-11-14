import { clockTime } from "@/lib/clockTime";
import type { DailyCalendar } from "@/lib/daily.types";

const WEEKDAYS = ["вс", "пн", "вт", "ср", "чт", "пт", "сб"];
const MS_IN_DAY = 24 * 60 * 60 * 1000;

/** Названия ближних дней по сдвигу от сегодня; остальные дни — датой. */
const RELATIVE_DAY_NAMES: Record<number, string> = {
  1: "Завтра",
  0: "Сегодня",
  [-1]: "Вчера",
  [-2]: "Позавчера",
};

/** `YYYY-MM-DD` → полночь этой даты в UTC: разница дат не зависит от пояса браузера. */
function parseDay(day: string): Date {
  return new Date(`${day}T00:00:00Z`);
}

function daysBetween(from: string, to: string): number {
  return Math.round((parseDay(to).getTime() - parseDay(from).getTime()) / MS_IN_DAY);
}

/** «16.11, пн». */
export function formatDay(day: string): string {
  const date = parseDay(day);
  const dd = String(date.getUTCDate()).padStart(2, "0");
  const mm = String(date.getUTCMonth() + 1).padStart(2, "0");
  return `${dd}.${mm}, ${WEEKDAYS[date.getUTCDay()]}`;
}

/** «Завтра», «Сегодня», «Вчера», «Позавчера»; у дальних дней названия нет. */
export function relativeDayName(day: string, calendar: Pick<DailyCalendar, "today">): string | undefined {
  return RELATIVE_DAY_NAMES[daysBetween(calendar.today, day)];
}

/** Название ближнего дня или дата — для дней «Истории». */
export function dayLabel(day: string, calendar: Pick<DailyCalendar, "today">): string {
  return relativeDayName(day, calendar) ?? formatDay(day);
}

/** «Сегодня · 16.11, пн» или «09.11, пн». */
export function fullDayLabel(day: string, calendar: Pick<DailyCalendar, "today">): string {
  const name = relativeDayName(day, calendar);
  return name ? `${name} · ${formatDay(day)}` : formatDay(day);
}

/** Подписи дней для выбора дня — в порядке `history_days`. */
export function historyDayLabels(calendar: DailyCalendar): Record<string, string> {
  return Object.fromEntries(calendar.history_days.map((day) => [day, dayLabel(day, calendar)]));
}

/** «10:00–11:30», «с 10:00» или пусто — время события по Москве. */
export function eventTimeRange(start: string | null, end: string | null): string {
  if (!start) return "";
  const from = clockTime(start);
  return end ? `${from}–${clockTime(end)}` : `с ${from}`;
}

/** Раздел 15.1: фильтр дашборда по отметкам задач. */
export type MarkDayKey = "yesterday" | "today" | "tomorrow";

export const MARK_DAY_KEYS: readonly MarkDayKey[] = ["yesterday", "today", "tomorrow"];

export const MARK_DAY_LABEL: Record<MarkDayKey, string> = {
  yesterday: "Вчера",
  today: "Сегодня",
  tomorrow: "Завтра",
};
