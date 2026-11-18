import { CalendarDays } from "lucide-react";
import { FeedNotice } from "@/components/tasks/FeedNotice";
import { formatFeedDate } from "@/lib/utils";

/** Раздел 15.2: служебная строка ленты — с этой даты идут следующие реплики. */
export function DateSeparator({ at }: { at: number }) {
  return (
    <FeedNotice icon={CalendarDays} role="separator" className="font-bold">
      <time dateTime={new Date(at).toISOString()}>{formatFeedDate(at)}</time>
    </FeedNotice>
  );
}
