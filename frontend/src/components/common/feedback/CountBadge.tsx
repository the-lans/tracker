import { cn } from "@/lib/utils";

/**
 * Счётчик в навигации (раздел 18.3: задачи, ожидающие решения); при нуле
 * не показывается.
 */
/** `max` — предел показа: больше него в кружке «99+», чтобы он не раздувался на узких экранах. */
export function CountBadge({ count, max, className }: { count?: number; max?: number; className?: string }) {
  if (!count) return null;
  return (
    <span
      className={cn(
        "rounded-full bg-danger px-[7px] py-px text-caption font-bold text-on-danger",
        className,
      )}
    >
      {max !== undefined && count > max ? `${max}+` : count}
    </span>
  );
}
