import { cn } from "@/lib/utils";

/** Индикатор загрузки списка или раздела. */
export function LoadingState({ label = "Загрузка…", className }: { label?: string; className?: string }) {
  return (
    <div role="status" className={cn("py-6 text-center text-body text-text-3", className)}>
      {label}
    </div>
  );
}
