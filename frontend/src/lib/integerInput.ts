export type ParsedInteger = { valid: true; value: number } | { valid: false };

/**
 * Целое число из поля ввода в границах `min`–`max`. Пустое поле недопустимо:
 * `Number("")` дал бы 0, а у сроков хранения 0 — «бессрочно».
 */
export function parseIntegerInRange(draft: string, min: number, max: number): ParsedInteger {
  if (draft.trim() === "") return { valid: false };
  const value = Number(draft);
  if (!Number.isInteger(value) || value < min || value > max) return { valid: false };
  return { valid: true, value };
}
