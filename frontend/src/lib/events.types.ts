/** Раздел 18.4: лента пользователя или общая лента администраторов. */
export const EventAudience = {
  USER: "user",
  ADMINS: "admins",
} as const;
export type EventAudience = (typeof EventAudience)[keyof typeof EventAudience];

export const EventCategory = {
  TASK: "task",
  LLM_ACCOUNT: "llm_account",
  PERIODIC: "periodic",
  BACKUP: "backup",
  PROFILE: "profile",
} as const;
export type EventCategory = (typeof EventCategory)[keyof typeof EventCategory];

export interface TrackerEvent {
  id: string;
  created_at: string;
  audience: EventAudience;
  category: EventCategory;
  /** Значение события уведомлений (раздел 18.2), например `done` или `backup_failed`. */
  event_type: string;
  title: string;
  body: string;
  task_id: string | null;
}

export interface EventFilters {
  audience: EventAudience;
  category?: EventCategory;
}

/** Категории ленты пользователя и ленты администраторов. */
export const USER_EVENT_CATEGORIES: EventCategory[] = [
  EventCategory.TASK,
  EventCategory.LLM_ACCOUNT,
  EventCategory.PROFILE,
];
export const ADMIN_EVENT_CATEGORIES: EventCategory[] = [EventCategory.BACKUP, EventCategory.PERIODIC];
