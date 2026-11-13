import type { User } from "@/lib/types";

export type UserNumberField = "max_parallel_tasks" | "archive_after_days" | "cleanup_repos_after_days";

/** Числовая настройка пользователя, которую задаёт администратор (раздел 15.5). */
export interface UserNumberSetting {
  field: UserNumberField;
  label: string;
  min: number;
  max: number;
  /** Пустое поле — `null`: настройка выключена. */
  nullable: boolean;
  errorMessage: string;
}

/** Границы — как у `UserUpdateRequest` backend. */
export const MAX_PARALLEL_TASKS_SETTING: UserNumberSetting = {
  field: "max_parallel_tasks",
  label: "Параллельных задач",
  min: 1,
  max: 50,
  nullable: false,
  errorMessage: "Не удалось сохранить лимит",
};

/** Раздел 14.2: сроки считаются от перехода задачи в «Готово»/«Ошибка». */
export const RETENTION_SETTINGS: readonly UserNumberSetting[] = [
  {
    field: "archive_after_days",
    label: "В архив через, дн.",
    min: 1,
    max: 3650,
    nullable: true,
    errorMessage: "Не удалось сохранить срок архивации",
  },
  {
    field: "cleanup_repos_after_days",
    label: "Очистка репозиториев через, дн.",
    min: 1,
    max: 3650,
    nullable: true,
    errorMessage: "Не удалось сохранить срок очистки репозиториев",
  },
];

export type ParsedSetting = { valid: true; value: number | null } | { valid: false };

export function parseSetting(draft: string, setting: UserNumberSetting): ParsedSetting {
  if (draft.trim() === "") return setting.nullable ? { valid: true, value: null } : { valid: false };
  const value = Number(draft);
  if (!Number.isInteger(value) || value < setting.min || value > setting.max) return { valid: false };
  return { valid: true, value };
}

export function settingValue(user: User, setting: UserNumberSetting): number | null {
  return user[setting.field];
}
