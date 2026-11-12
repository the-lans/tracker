import type { ReactNode } from "react";
import { Card, CardTitle } from "@/components/ui/card";
import { QueryState } from "@/components/common/feedback/QueryState";
import { cn } from "@/lib/utils";

/** Карточка блока «Мониторинга»: заголовок, загрузка и ошибка запроса блока. */
export function MonitoringCard({
  title,
  action,
  isLoading,
  isError,
  className,
  children,
}: {
  title: string;
  action?: ReactNode;
  isLoading: boolean;
  isError: boolean;
  className?: string;
  children: ReactNode;
}) {
  return (
    <Card className={cn("flex min-w-0 flex-col", className)}>
      <CardTitle className="flex-wrap gap-2">
        <h2>{title}</h2>
        {action}
      </CardTitle>
      <QueryState isLoading={isLoading} isError={isError} loadingClassName="py-3">
        {children}
      </QueryState>
    </Card>
  );
}
