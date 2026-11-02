import { LlmAccountStatus, type LlmAccount } from "@/lib/types";

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
