import type { ReactNode } from "react";

/**
 * Подпись кнопки со значком: на телефоне и на низком экране (альбомная
 * ориентация) остаётся только значок — имя кнопки задаёт `aria-label`.
 */
export function ButtonLabel({ children }: { children: ReactNode }) {
  return <span className="hidden sm:inline short:hidden">{children}</span>;
}
