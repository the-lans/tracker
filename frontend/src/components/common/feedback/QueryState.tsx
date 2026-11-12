import type { ReactNode } from "react";
import { ErrorState } from "@/components/common/feedback/ErrorState";
import { LoadingState } from "@/components/common/feedback/LoadingState";

/**
 * Состояние запроса: загрузка, сбой или содержимое. Содержимое не
 * показывается, пока идёт первая загрузка или запрос упал.
 */
export function QueryState({
  isLoading,
  isError,
  errorLabel,
  loadingClassName,
  children,
}: {
  isLoading: boolean;
  isError: boolean;
  errorLabel?: string;
  loadingClassName?: string;
  children: ReactNode;
}) {
  if (isLoading) return <LoadingState className={loadingClassName} />;
  if (isError) return <ErrorState label={errorLabel} />;
  return <>{children}</>;
}
