import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { formatFileSize, formatInterval, formatRelativeShort, initialsFromEmail, plural } from "@/lib/utils";

const MINUTE_FORMS: [string, string, string] = ["минута", "минуты", "минут"];

describe("plural", () => {
  it.each([
    [1, "минута"],
    [2, "минуты"],
    [4, "минуты"],
    [5, "минут"],
    [11, "минут"],
    [12, "минут"],
    [14, "минут"],
    [21, "минута"],
    [22, "минуты"],
    [111, "минут"],
    [0, "минут"],
  ])("%i → «%s»", (count, expected) => {
    expect(plural(count, MINUTE_FORMS)).toBe(expected);
  });
});

describe("formatInterval", () => {
  it.each([
    [300, "каждые 5 минут"],
    [120, "каждые 2 минуты"],
    [60, "каждую минуту"],
    [1260, "каждую 21 минуту"],
    [45, "каждые 45 секунд"],
    [1, "каждую секунду"],
    [21, "каждую 21 секунду"],
    [3600, "каждый час"],
    [7200, "каждые 2 часа"],
    [5400, "каждые 90 минут"],
    [86400, "каждый день"],
    [604800, "каждую неделю"],
    [1209600, "каждые 2 недели"],
  ])("%i с → «%s»", (seconds, expected) => {
    expect(formatInterval(seconds)).toBe(expected);
  });
});

describe("formatFileSize", () => {
  it.each([
    [0, "0 Б"],
    [1023, "1023 Б"],
    [1024, "1 КБ"],
    [1536, "1,5 КБ"],
    [10 * 1024 + 512, "11 КБ"],
    [1024 * 1024 - 1, "1 МБ"],
    [3.4 * 1024 * 1024, "3,4 МБ"],
    [5 * 1024 ** 4, "5120 ГБ"],
  ])("%i байт → «%s»", (bytes, expected) => {
    // Разделитель тысяч у ru-RU — неразрывный пробел; сравниваем без него.
    expect(formatFileSize(bytes).replace(/\s(?=\d)/g, "")).toBe(expected);
  });
});

describe("formatRelativeShort", () => {
  const NOW = new Date("2026-10-25T12:00:00Z");

  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(NOW);
  });
  afterEach(() => vi.useRealTimers());

  it.each([
    [null, "—"],
    ["2026-10-25T11:59:30Z", "30 с назад"],
    ["2026-10-25T11:59:00Z", "1 мин назад"],
    ["2026-10-25T11:00:01Z", "59 мин назад"],
    ["2026-10-25T11:00:00Z", "1 ч назад"],
    ["2026-10-24T12:00:01Z", "23 ч назад"],
    ["2026-10-24T12:00:00Z", "1 дн назад"],
    ["2026-10-25T12:05:00Z", "0 с назад"],
  ])("%s → «%s»", (value, expected) => {
    expect(formatRelativeShort(value)).toBe(expected);
  });
});

describe("initialsFromEmail", () => {
  it.each([
    ["anna.petrova@example.com", "AP"],
    ["oleg_ivanov@example.com", "OI"],
    ["admin@example.com", "AD"],
  ])("%s → %s", (email, expected) => {
    expect(initialsFromEmail(email)).toBe(expected);
  });
});
