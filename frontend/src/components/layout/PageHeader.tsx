import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

export function PageHeader({
  title,
  actions,
  actionsClassName,
  children,
}: {
  title: string;
  actions?: ReactNode;
  actionsClassName?: string;
  children?: ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-center gap-4 px-5 pb-3 pt-3 short:pb-2 short:pt-2 lg:px-8 lg:pb-4 lg:pt-6">
      <h1 className="hidden text-display font-extrabold tracking-tight lg:block">{title}</h1>
      {children}
      {actions && <div className={cn("ml-auto flex items-center gap-2", actionsClassName)}>{actions}</div>}
    </div>
  );
}
