import { describe, expect, test } from "vitest";
import { dayLabel, eventTimeRange, formatDay, fullDayLabel } from "@/lib/dailyDays";

const CALENDAR = { today: "2026-11-16" };

describe("dailyDays", () => {
  test.for([
    { day: "2026-11-17", label: "Завтра" },
    { day: "2026-11-16", label: "Сегодня" },
    { day: "2026-11-15", label: "Вчера" },
    { day: "2026-11-14", label: "Позавчера" },
    { day: "2026-11-13", label: "13.11, пт" },
    // Переход через границу месяца и года не сбивает счёт дней.
    { day: "2026-12-31", label: "31.12, чт" },
  ])("$day → «$label»", ({ day, label }) => {
    expect(dayLabel(day, CALENDAR)).toBe(label);
  });

  test("у ближнего дня — и название, и дата", () => {
    expect(fullDayLabel("2026-11-16", CALENDAR)).toBe("Сегодня · 16.11, пн");
    expect(fullDayLabel("2026-11-09", CALENDAR)).toBe(formatDay("2026-11-09"));
  });

  test.for([
    { start: "10:00:00", end: "11:30:00", range: "10:00–11:30" },
    { start: "10:00:00", end: null, range: "с 10:00" },
    { start: null, end: null, range: "" },
  ])("время $start–$end → «$range»", ({ start, end, range }) => {
    expect(eventTimeRange(start, end)).toBe(range);
  });
});
