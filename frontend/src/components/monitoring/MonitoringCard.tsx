import type { ReactNode } from "react";
import { Card, CardTitle } from "@/components/ui/card";
import { LoadingState } from "@/components/common/feedback/LoadingState";
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
      {isLoading && <LoadingState className="py-3" />}
      {isError && <div className="text-body text-danger-text">Не удалось получить данные</div>}
      {!isLoading && !isError && children}
    </Card>
  );
}
