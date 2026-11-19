import type { ReactNode } from "react";
import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * Служебная строка ленты чата (раздел 15.2): значок и короткий текст по центру —
 * смена аккаунта, сброс контекста, новая сессия, дата. Сообщения самих ходов — `MessageBubble`.
 */
export function FeedNotice({
  icon: Icon,
  role = "note",
  className,
  children,
}: {
  icon: LucideIcon;
  /** `note` — событие, `separator` — граница дат. */
  role?: "note" | "separator";
  className?: string;
  children: ReactNode;
}) {
  return (
    <div
      role={role}
      className={cn(
        "flex items-center justify-center gap-1.5 text-center text-caption text-text-3",
        className,
      )}
    >
      <Icon className="size-3 shrink-0" />
      <span>{children}</span>
    </div>
  );
}
