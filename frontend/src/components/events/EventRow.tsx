import { Link } from "react-router-dom";
import { Archive, Bell, CalendarClock, KeySquare, ListChecks, UserRound, type LucideIcon } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { EventCategory, type TrackerEvent } from "@/lib/events.types";
import { EVENT_CATEGORY_LABEL, eventTone } from "@/lib/labels";
import { formatDateTime } from "@/lib/utils";

const CATEGORY_ICON: Record<EventCategory, LucideIcon> = {
  [EventCategory.TASK]: ListChecks,
  [EventCategory.LLM_ACCOUNT]: KeySquare,
  [EventCategory.PERIODIC]: CalendarClock,
  [EventCategory.BACKUP]: Archive,
  [EventCategory.PROFILE]: UserRound,
};

/** Раздел 18.4: строка ленты — категория, время, заголовок, подробности и ссылка на задачу. */
export function EventRow({ event }: { event: TrackerEvent }) {
  const Icon = CATEGORY_ICON[event.category] ?? Bell;
  return (
    <li className="flex min-w-0 gap-3 rounded-lg border border-border bg-surface p-3">
      <div className="flex size-8 shrink-0 items-center justify-center rounded-full bg-surface-2 text-text-2">
        <Icon className="size-4" aria-label={EVENT_CATEGORY_LABEL[event.category]} />
      </div>
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
          <Badge tone={eventTone(event.event_type)}>{event.title}</Badge>
          <time dateTime={event.created_at} className="text-caption text-text-3">
            {formatDateTime(event.created_at)}
          </time>
        </div>
        {event.body && <div className="min-w-0 break-words text-body text-text">{event.body}</div>}
        {event.task_id && (
          <Link to={`/tasks/${event.task_id}`} className="touch-target inline-flex w-fit items-center text-small font-bold text-accent">
            Открыть задачу
          </Link>
        )}
      </div>
    </li>
  );
}
