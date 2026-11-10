import { LlmAccountStatus, LlmLimitState, type LlmAccount } from "@/lib/types";
import { formatResetTime } from "@/lib/utils";

/**
 * Раздел 3.1, 15.2: пункт «Автоматически» выбора стартового аккаунта — в
 * задаче он хранится пустым значением (у пункта Select пустого значения быть не может).
 */
export const AUTO_ACCOUNT = "auto";
export const AUTO_ACCOUNT_LABEL = "Автоматически";

/** Раздел 3.1: у автора задачи нет аккаунта, который может работать. */
export const NO_LLM_ACCOUNT = "Нет доступного LLM-аккаунта";

/** Аккаунты, из которых выбирают стартовый аккаунт задачи. */
export interface StartAccountOptions {
  /** Все аккаунты автора задачи — пусто, если он ещё не завёл ни одного. */
  own: LlmAccount[];
  /** Варианты выбора: `active` по порядку переключения и уже выбранный. */
  choices: LlmAccount[];
}

/**
 * Раздел 19.2: у задачи — только аккаунт её автора (`admin` видит и чужие).
 * Раздел 15.2: стартовый — из `active` по порядку переключения; уже выбранный
 * не пропадает, даже если его потом выключили.
 */
export function startAccountOptions(
  accounts: LlmAccount[],
  ownerId: string | undefined,
  selectedId: string | null,
): StartAccountOptions {
  const own = accounts.filter((account) => account.created_by === ownerId);
  const choices = own.filter(
    (account) => account.status === LlmAccountStatus.ACTIVE || account.id === selectedId,
  );
  return { own, choices };
}

/**
 * Раздел 3.1, 19.7: у автора есть аккаунт, который может работать, — тогда
 * задача без стартового аккаунта выбирает его автоматически.
 */
export function hasUsableAccount(accounts: LlmAccount[], ownerId: string | undefined): boolean {
  return accounts.some(
    (account) => account.created_by === ownerId && account.limit_state !== LlmLimitState.EXCLUDED,
  );
}

/** Раздел 15.2: подсказка у запуска, пока задачи автора ждут сброса лимита. */
export function launchWaitHint(waitUntil: string): string {
  return `Все LLM-аккаунты на пороге — задача начнёт работу в ${formatResetTime(waitUntil)}`;
}
