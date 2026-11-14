import type { TaskStatus } from "@/lib/types";

/** Раздел 15.8: дни «Дейли» по началу дня из системных настроек (даты — `YYYY-MM-DD`). */
export interface DailyCalendar {
  today: string;
  yesterday: string;
  tomorrow: string;
  /** Завтра, сегодня и 7 прошлых дней — от новых к старым. */
  history_days: string[];
  day_start_time: string;
}

export interface TaskDayMarks {
  task_id: string;
  days: string[];
}

/** Что было по отмеченной задаче за день; `null` — день ещё не наступил. */
export type DayFact = "done" | "failed" | "worked" | "no_work";

export interface DailyMarkedTask {
  id: string;
  code: string;
  title: string;
  status: TaskStatus;
  fact: DayFact | null;
}

export type DailyEventSource = "manual" | "google";

export interface DailyEvent {
  id: string;
  source: DailyEventSource;
  day: string;
  end_day: string;
  starts_at: string | null;
  ends_at: string | null;
  /** Время по Москве, `HH:MM:SS`. */
  start_time: string | null;
  end_time: string | null;
  title: string;
  notes: string | null;
  hidden: boolean;
}

export interface DailyDay {
  day: string;
  tasks: DailyMarkedTask[];
  events: DailyEvent[];
}

export interface DailyEventRequest {
  day: string;
  title: string;
  notes: string | null;
  start_time: string | null;
  end_time: string | null;
}

export interface DailyPlan {
  id: string;
  day: string;
  content: string;
  created_at: string;
  updated_at: string;
}

export interface DailyTemplate {
  content: string;
  is_default: boolean;
  variables: string[];
}

export type GoogleCalendarStatus = "connected" | "needs_reauth";

/** Раздел 19.8: подключение к Google Calendar; `null` — не подключён. */
export interface GoogleCalendarConnection {
  google_email: string;
  status: GoogleCalendarStatus;
  calendar_ids: string[];
  last_synced_at: string | null;
  last_error: string | null;
}

export interface GoogleCalendarInfo {
  id: string;
  summary: string;
  primary: boolean;
}

export interface GoogleCalendarSyncResult {
  synced: boolean;
  events: number;
}
