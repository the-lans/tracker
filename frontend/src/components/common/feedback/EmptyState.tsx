import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * Пустой список: что здесь будет и как это добавить. `compact` — внутри
 * карточки (без значка и крупных отступов), иначе — на всю область страницы.
 */
export function EmptyState({
  icon: Icon,
  title,
  hint,
  compact = false,
}: {
  icon?: LucideIcon;
  title: string;
  hint?: string;
  compact?: boolean;
}) {
  if (compact) {
    return (
      <div className="py-2 text-note">
        <div className="font-bold text-text-2">{title}</div>
        {hint && <div className="mt-0.5 text-text-3">{hint}</div>}
      </div>
    );
  }
  return (
    <div className={cn("flex flex-col items-center px-4 py-12 text-center")}>
      {Icon && (
        <div className="mb-3 flex size-11 items-center justify-center rounded-full border border-accent-border bg-accent-tint text-accent">
          <Icon className="size-5" />
        </div>
      )}
      <div className="text-lead font-bold text-text">{title}</div>
      {hint && <div className="mt-1 max-w-sm text-body text-text-3">{hint}</div>}
    </div>
  );
}
