/** Ширина бокового меню на компьютере: границы, «схлопывание» до значков и хранение между сеансами. */

const STORAGE_KEY = "tracker.sidebarWidth";

/** Ширина меню только со значками. */
export const SIDEBAR_COMPACT_WIDTH = 72;
export const SIDEBAR_DEFAULT_WIDTH = 248;
export const SIDEBAR_MAX_WIDTH = 420;
/** Уже этой ширины подписи не помещаются: меню схлопывается до значков. */
export const SIDEBAR_COLLAPSE_BELOW = 160;
/** Шаг стрелок клавиатуры. */
export const SIDEBAR_KEY_STEP = 16;

/** Приводит ширину к допустимой: всё, что уже порога, — меню со значками. */
export function normalizeSidebarWidth(width: number): number {
  if (!Number.isFinite(width)) return SIDEBAR_DEFAULT_WIDTH;
  if (width < SIDEBAR_COLLAPSE_BELOW) return SIDEBAR_COMPACT_WIDTH;
  return Math.min(Math.round(width), SIDEBAR_MAX_WIDTH);
}

export function isSidebarCompact(width: number): boolean {
  return width <= SIDEBAR_COMPACT_WIDTH;
}

/** Ширина после нажатия стрелки: из режима значков меню раскрывается сразу до порога. */
export function stepSidebarWidth(width: number, direction: 1 | -1): number {
  if (isSidebarCompact(width)) {
    return direction > 0 ? SIDEBAR_COLLAPSE_BELOW : SIDEBAR_COMPACT_WIDTH;
  }
  return normalizeSidebarWidth(width + direction * SIDEBAR_KEY_STEP);
}

export function readStoredSidebarWidth(): number {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored !== null) return normalizeSidebarWidth(Number(stored));
  } catch {
    // хранилище недоступно — берём ширину по умолчанию
  }
  return SIDEBAR_DEFAULT_WIDTH;
}

export function storeSidebarWidth(width: number): void {
  try {
    localStorage.setItem(STORAGE_KEY, String(width));
  } catch {
    // приватный режим и т.п. — ширина просто не переживёт перезагрузку
  }
}
