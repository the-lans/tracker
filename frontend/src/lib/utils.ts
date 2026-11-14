import { clsx, type ClassValue } from "clsx";
import { extendTailwindMerge } from "tailwind-merge";

/** Типографическая шкала из index.css (`--text-*`) — чтобы `cn` не путал её с цветом текста. */
export const FONT_SIZE_SCALE = [
  "caption",
  "meta",
  "small",
  "note",
  "body",
  "body-lg",
  "lead",
  "card-title",
  "subtitle",
  "title",
  "heading",
  "display",
] as const;

const twMerge = extendTailwindMerge({ extend: { theme: { text: [...FONT_SIZE_SCALE] } } });

export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}

/** Граница дня `<input type="date">` в локальной зоне — в ISO для API; конец дня — начало следующего. */
export function localDayBoundary(value: string, endOfDay: boolean): string | undefined {
  if (!value) return undefined;
  const date = new Date(`${value}T00:00:00`);
  if (endOfDay) date.setDate(date.getDate() + 1);
  return date.toISOString();
}

/** Число страниц списка; пустой список — одна страница. */
export function pageCountOf(total: number, pageSize: number): number {
  return Math.max(1, Math.ceil(total / pageSize));
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  return date.toLocaleString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    year: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/**
 * Раздел 19.7: момент сброса лимита — время, если сегодня («18:40»), иначе
 * с датой («14 нояб., 18:40»).
 */
export function formatResetTime(value: string, now: Date = new Date()): string {
  const date = new Date(value);
  const time = date.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
  if (date.toDateString() === now.toDateString()) return time;
  return `${date.toLocaleDateString("ru-RU", { day: "numeric", month: "short" })}, ${time}`;
}

export function formatRelativeShort(value: string | null | undefined, now: number = Date.now()): string {
  if (!value) return "—";
  const then = new Date(value).getTime();
  const diffSeconds = Math.max(0, Math.floor((now - then) / 1000));
  if (diffSeconds < 60) return `${diffSeconds} с назад`;
  const diffMinutes = Math.floor(diffSeconds / 60);
  if (diffMinutes < 60) return `${diffMinutes} мин назад`;
  const diffHours = Math.floor(diffMinutes / 60);
  if (diffHours < 24) return `${diffHours} ч назад`;
  const diffDays = Math.floor(diffHours / 24);
  return `${diffDays} дн назад`;
}

export function initialsFromEmail(email: string): string {
  const namePart = email.split("@")[0] ?? email;
  const segments = namePart.split(/[._-]/).filter(Boolean);
  if (segments.length >= 2) {
    return (segments[0]![0]! + segments[1]![0]!).toUpperCase();
  }
  return namePart.slice(0, 2).toUpperCase();
}

/** Русская форма слова для числа: plural(5, ["минута", "минуты", "минут"]) → «минут». */
export function plural(count: number, forms: [string, string, string]): string {
  const mod100 = count % 100;
  const mod10 = count % 10;
  if (mod100 >= 11 && mod100 <= 14) return forms[2];
  if (mod10 === 1) return forms[0];
  if (mod10 >= 2 && mod10 <= 4) return forms[1];
  return forms[2];
}

const INTERVAL_UNITS: Array<{ seconds: number; single: string; forms: [string, string, string] }> = [
  { seconds: 7 * 86400, single: "каждую неделю", forms: ["неделю", "недели", "недель"] },
  { seconds: 86400, single: "каждый день", forms: ["день", "дня", "дней"] },
  { seconds: 3600, single: "каждый час", forms: ["час", "часа", "часов"] },
  { seconds: 60, single: "каждую минуту", forms: ["минуту", "минуты", "минут"] },
  { seconds: 1, single: "каждую секунду", forms: ["секунду", "секунды", "секунд"] },
];

/** Интервал периодической задачи словами: 300 → «каждые 5 минут», 604800 → «каждую неделю». */
export function formatInterval(seconds: number): string {
  for (const unit of INTERVAL_UNITS) {
    if (seconds % unit.seconds !== 0) continue;
    const count = seconds / unit.seconds;
    if (count === 1) return unit.single;
    return `${plural(count, ["каждую", "каждые", "каждые"])} ${count} ${plural(count, unit.forms)}`;
  }
  return `каждые ${seconds} с`;
}

const SECONDS_PER_MINUTE = 60;

/** Обратный отсчёт «минуты:секунды»: 245 → «4:05». */
export function formatCountdown(seconds: number): string {
  const minutes = Math.floor(seconds / SECONDS_PER_MINUTE);
  const rest = String(seconds % SECONDS_PER_MINUTE).padStart(2, "0");
  return `${minutes}:${rest}`;
}

const FILE_SIZE_UNITS = ["Б", "КБ", "МБ", "ГБ"] as const;
const FILE_SIZE_STEP = 1024;
/** Ниже этого значения размер показывается с одной цифрой после запятой: «3,4 МБ». */
const FILE_SIZE_FRACTION_BELOW = 10;

function fileSizeDigits(value: number, unit: number): number {
  return unit === 0 || value >= FILE_SIZE_FRACTION_BELOW ? 0 : 1;
}

function roundFileSize(value: number, unit: number): number {
  const factor = 10 ** fileSizeDigits(value, unit);
  return Math.round(value * factor) / factor;
}

/** Размер файла для списка артефактов (раздел 15.2): «12 КБ», «3,4 МБ». */
export function formatFileSize(bytes: number): string {
  let value = bytes;
  let unit = 0;
  // Сравнивается округлённое значение: 1023,9 КБ показывается как «1 МБ», а не «1024 КБ».
  while (roundFileSize(value, unit) >= FILE_SIZE_STEP && unit < FILE_SIZE_UNITS.length - 1) {
    value /= FILE_SIZE_STEP;
    unit += 1;
  }
  const digits = fileSizeDigits(value, unit);
  return `${value.toLocaleString("ru-RU", { maximumFractionDigits: digits })} ${FILE_SIZE_UNITS[unit]}`;
}

const SECONDS_PER_HOUR = 3600;

/** Длительность словами: 45 → «45 с», 200 → «3 мин 20 с», 3900 → «1 ч 5 мин». */
export function formatDuration(totalSeconds: number): string {
  const seconds = Math.round(totalSeconds);
  if (seconds < SECONDS_PER_MINUTE) return `${seconds} с`;
  const hours = Math.floor(seconds / SECONDS_PER_HOUR);
  const minutes = Math.floor((seconds % SECONDS_PER_HOUR) / SECONDS_PER_MINUTE);
  if (hours > 0) return minutes > 0 ? `${hours} ч ${minutes} мин` : `${hours} ч`;
  const rest = seconds % SECONDS_PER_MINUTE;
  return rest > 0 ? `${minutes} мин ${rest} с` : `${minutes} мин`;
}
