import { cn } from "@/lib/utils";

/** Число с подписью в сетке показателей карточки. */
export function StatTile({
  label,
  value,
  tone = "default",
}: {
  label: string;
  value: string | number;
  tone?: "default" | "danger" | "warning" | "success";
}) {
  return (
    <div className="flex min-w-0 flex-col gap-0.5 rounded-md bg-surface-2 px-3 py-2">
      <span className="truncate text-caption text-text-3">{label}</span>
      <span
        className={cn(
          "text-title font-extrabold tabular-nums text-text",
          tone === "danger" && "text-danger-text",
          tone === "warning" && "text-warning-text",
          tone === "success" && "text-success-text",
        )}
      >
        {value}
      </span>
    </div>
  );
}
