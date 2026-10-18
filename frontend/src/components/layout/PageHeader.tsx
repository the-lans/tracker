import type { ReactNode } from "react";

export function PageHeader({
  title,
  actions,
  children,
}: {
  title: string;
  actions?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-center gap-4 px-5 pb-4 pt-5 lg:px-8 lg:pt-6">
      <h1 className="hidden text-[22px] font-extrabold tracking-tight lg:block">{title}</h1>
      {children}
      {actions && <div className="ml-auto flex items-center gap-2">{actions}</div>}
    </div>
  );
}
