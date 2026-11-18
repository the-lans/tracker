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

// `relative`: скрытые служебные поля переключателей и списков (position: absolute)
// остаются внутри панели прокрутки и не растягивают документ — иначе второй ползунок.
export const PAGE_BODY =
  "relative min-h-0 flex-1 overflow-auto px-5 pb-8 short:flex-none short:overflow-visible lg:px-8";

/** Кнопка действия в шапке страницы задачи (раздел 14.2). */
export const HEADER_BUTTON =
  "flex touch-target items-center justify-center gap-2 whitespace-nowrap rounded-md border border-border bg-surface px-3 py-2 text-body font-bold text-text-2 transition-colors hover:border-accent hover:bg-accent-tint hover:text-accent focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:pointer-events-none disabled:opacity-50 short:py-1";

/** Градиент аватара пользователя — один и тот же в меню, профиле и ленте. */
export const USER_AVATAR_GRADIENT = "bg-gradient-to-br from-avatar-from to-avatar-to text-white";

/** Строка из подписи, бейджей и пояснений, переносящаяся на узком экране. */
export const WRAP_ROW = "flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1";

/** Нижняя часть карточки, отделённая чертой от основного содержимого. */
export const CARD_DIVIDER = "border-t border-border pt-3";
