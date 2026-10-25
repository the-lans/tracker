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

export function formatRelativeShort(value: string | null | undefined): string {
  if (!value) return "—";
  const then = new Date(value).getTime();
  const now = Date.now();
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

const FILE_SIZE_UNITS = ["Б", "КБ", "МБ", "ГБ"] as const;
const FILE_SIZE_STEP = 1024;

/** Размер файла для списка артефактов (раздел 15.2): «12 КБ», «3,4 МБ». */
export function formatFileSize(bytes: number): string {
  let value = bytes;
  let unit = 0;
  const digitsOf = (current: number, currentUnit: number) => (currentUnit === 0 || current >= 10 ? 0 : 1);
  const rounded = (current: number, currentUnit: number) => {
    const factor = 10 ** digitsOf(current, currentUnit);
    return Math.round(current * factor) / factor;
  };
  // Сравнивается округлённое значение: 1023,9 КБ показывается как «1 МБ», а не «1024 КБ».
  while (rounded(value, unit) >= FILE_SIZE_STEP && unit < FILE_SIZE_UNITS.length - 1) {
    value /= FILE_SIZE_STEP;
    unit += 1;
  }
  const digits = digitsOf(value, unit);
  return `${value.toLocaleString("ru-RU", { maximumFractionDigits: digits })} ${FILE_SIZE_UNITS[unit]}`;
}
