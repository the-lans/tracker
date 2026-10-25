import { cn } from "@/lib/utils";

/**
 * Счётчик в навигации (раздел 18.3: задачи, ожидающие решения); при нуле
 * не показывается.
 */
export function CountBadge({ count, className }: { count?: number; className?: string }) {
  if (!count) return null;
  return (
    <span
      className={cn(
        "rounded-full bg-danger px-[7px] py-px text-caption font-bold text-on-danger",
        className,
      )}
    >
      {count}
    </span>
  );
}
