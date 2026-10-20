import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

/** Заголовок раздела внутри страницы (подразделы администрирования и т. п.). */
export function SectionTitle({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cn("text-note font-extrabold text-text-2", className)}>{children}</div>;
}
