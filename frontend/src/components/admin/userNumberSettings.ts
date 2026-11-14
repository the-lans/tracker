import { parseIntegerInRange, type ParsedInteger } from "@/lib/integerInput";
import { MAX_RETENTION_DAYS, RETENTION_FOREVER, type User } from "@/lib/types";

export type UserNumberField =
  | "max_parallel_tasks"
  | "archive_after_days"
  | "cleanup_repos_after_days"
  | "artifacts_retention_days";

/** Числовая настройка пользователя, которую задаёт администратор (раздел 15.5). */
export interface UserNumberSetting {
  field: UserNumberField;
  label: string;
  min: number;
  max: number;
  /** `RETENTION_FOREVER` — срок выключен, рядом с полем подпись «бессрочно». */
  zeroMeansForever: boolean;
  errorMessage: string;
}

/** Границы — как у `UserUpdateRequest` backend. */
export const MAX_PARALLEL_TASKS_SETTING: UserNumberSetting = {
  field: "max_parallel_tasks",
  label: "Параллельных задач",
  min: 1,
  max: 50,
  zeroMeansForever: false,
  errorMessage: "Не удалось сохранить лимит",
};

const RETENTION_RANGE = {
  min: RETENTION_FOREVER,
  max: MAX_RETENTION_DAYS,
  zeroMeansForever: true,
} as const;

/** Разделы 14.2, 14.3: сроки считаются от перехода задачи в «Готово»/«Ошибка». */
export const RETENTION_SETTINGS: readonly UserNumberSetting[] = [
  {
    field: "archive_after_days",
    label: "В архив через, дн.",
    ...RETENTION_RANGE,
    errorMessage: "Не удалось сохранить срок архивации",
  },
  {
    field: "cleanup_repos_after_days",
    label: "Очистка репозиториев через, дн.",
    ...RETENTION_RANGE,
    errorMessage: "Не удалось сохранить срок очистки репозиториев",
  },
  {
    field: "artifacts_retention_days",
    label: "Артефакты архива хранятся, дн.",
    ...RETENTION_RANGE,
    errorMessage: "Не удалось сохранить срок хранения артефактов",
  },
];

export function parseSetting(draft: string, setting: UserNumberSetting): ParsedInteger {
  return parseIntegerInRange(draft, setting.min, setting.max);
}

export function settingValue(user: User, setting: UserNumberSetting): number {
  return user[setting.field];
}

/** Подпись выключенного срока рядом с полем. */
export function isForever(value: number, setting: UserNumberSetting): boolean {
  return setting.zeroMeansForever && value === RETENTION_FOREVER;
}
