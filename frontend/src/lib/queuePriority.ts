/** Раздел 14.4: границы приоритета — как у `queue_priority` backend. */
export const MIN_QUEUE_PRIORITY = 1;
export const MAX_QUEUE_PRIORITY = 1_000_000;
export const DEFAULT_QUEUE_PRIORITY = 100;

export const QUEUE_PRIORITY_RANGE_HINT = `Целое число от ${MIN_QUEUE_PRIORITY} до ${MAX_QUEUE_PRIORITY.toLocaleString("ru-RU")}`;
export const QUEUE_PRIORITY_HINT = "Больше — раньше; при равном приоритете — кто встал в очередь раньше";

/** Введённый приоритет или `null`, если он вне допустимых границ. */
export function parseQueuePriority(draft: string): number | null {
  const value = Number(draft);
  if (!Number.isInteger(value) || value < MIN_QUEUE_PRIORITY || value > MAX_QUEUE_PRIORITY) return null;
  return value;
}
