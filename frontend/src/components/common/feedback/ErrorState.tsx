import { cn } from "@/lib/utils";

/** Сбой запроса списка или раздела. */
export function ErrorState({
  label = "Не удалось получить данные",
  className,
}: {
  label?: string;
  className?: string;
}) {
  return (
    <div role="alert" className={cn("text-body text-danger-text", className)}>
      {label}
    </div>
  );
}
