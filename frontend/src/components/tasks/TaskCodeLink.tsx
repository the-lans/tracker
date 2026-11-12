import { Link } from "react-router-dom";
import { cn } from "@/lib/utils";

/** Сколько символов id показывать, если код задачи неизвестен. */
const SHORT_ID_LENGTH = 8;

/**
 * Код задачи ссылкой на её страницу; без кода — начало id. Без id задачи
 * (запись ни к чему не привязана) — код простым текстом.
 */
export function TaskCodeLink({
  taskId,
  code,
  className,
}: {
  taskId: string | null;
  code?: string | null;
  className?: string;
}) {
  const label = code ?? taskId?.slice(0, SHORT_ID_LENGTH);
  if (!label) return null;
  const classes = cn("font-mono text-small font-bold", className);
  if (!taskId) return <span className={classes}>{label}</span>;
  return (
    <Link to={`/tasks/${taskId}`} className={cn("touch-target inline-flex items-center text-accent", classes)}>
      {label}
    </Link>
  );
}
