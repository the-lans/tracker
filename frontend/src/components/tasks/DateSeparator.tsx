import { CalendarDays } from "lucide-react";
import { formatFeedDate } from "@/lib/utils";

/** Раздел 15.2: служебная строка ленты — с этой даты идут следующие реплики. */
export function DateSeparator({ at }: { at: number }) {
  return (
    <div
      role="separator"
      className="flex items-center justify-center gap-1.5 text-center text-caption font-bold text-text-3"
    >
      <CalendarDays className="size-3 shrink-0" />
      <time dateTime={new Date(at).toISOString()}>{formatFeedDate(at)}</time>
    </div>
  );
}
