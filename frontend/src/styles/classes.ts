/**
 * Общие наборы классов Tailwind — повторяющееся оформление в одном месте.
 * Цвета и размеры шрифта берутся из токенов темы (styles/tokens.css, index.css).
 */

/**
 * Каркас обычной страницы: шапка сверху, ниже прокручиваемая область.
 * На низком экране (`short:`, телефон в альбомной ориентации) страница
 * прокручивается целиком, без закреплённых панелей.
 */
export const PAGE_ROOT = "flex h-full flex-col short:h-auto";

export const PAGE_BODY =
  "min-h-0 flex-1 overflow-auto px-5 pb-8 short:flex-none short:overflow-visible lg:px-8";

/** Кнопка действия в шапке страницы задачи (раздел 14.2). */
export const HEADER_BUTTON =
  "flex touch-target items-center justify-center gap-2 whitespace-nowrap rounded-md border border-border bg-surface px-3 py-2 text-body font-bold short:py-1 text-text-2 disabled:opacity-50";

/** Градиент аватара пользователя — один и тот же в меню, профиле и ленте. */
export const USER_AVATAR_GRADIENT = "bg-gradient-to-br from-avatar-from to-avatar-to text-white";
