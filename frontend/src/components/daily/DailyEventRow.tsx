import { CalendarDays, Eye, EyeOff } from "lucide-react";
import { ConfirmDeleteButton } from "@/components/common/actions/ConfirmDeleteButton";
import { EditButton } from "@/components/common/actions/EditButton";
import { useDeleteDailyEvent, useSetDailyEventHidden } from "@/hooks/useDaily";
import type { DailyEvent } from "@/lib/daily.types";
import { eventTimeRange } from "@/lib/dailyDays";
import { toastError } from "@/lib/errors";
import { cn } from "@/lib/utils";

/**
 * Событие дня: ручное правится и удаляется, событие календаря только
 * скрывается — его содержимое приходит из Google при синхронизации.
 */
export function DailyEventRow({ event, onEdit }: { event: DailyEvent; onEdit: (event: DailyEvent) => void }) {
  const setHidden = useSetDailyEventHidden(event.id);
  const deleteEvent = useDeleteDailyEvent();
  const time = eventTimeRange(event.start_time, event.end_time);
  const fromCalendar = event.source === "google";

  return (
    <li className={cn("flex items-start gap-2 py-2", event.hidden && "opacity-60")}>
      <div className="flex min-w-0 flex-1 flex-col sm:flex-row sm:gap-2">
        <div className="shrink-0 pt-0.5 text-small text-text-3 tabular-nums sm:w-24">{time || "весь день"}</div>
        <div className="min-w-0 flex-1">
          <div className="flex min-w-0 items-center gap-1.5">
            {fromCalendar && (
              <CalendarDays className="size-3.5 shrink-0 text-text-3" aria-label="Из Google Calendar" />
            )}
            <span className={cn("min-w-0 [overflow-wrap:anywhere] font-bold", event.hidden && "line-through")}>
              {event.title}
            </span>
          </div>
          {event.notes && (
            <div className="whitespace-pre-wrap [overflow-wrap:anywhere] text-small text-text-3">{event.notes}</div>
          )}
        </div>
      </div>
      {fromCalendar ? (
        <button
          type="button"
          aria-label={event.hidden ? `Показать ${event.title}` : `Скрыть ${event.title}`}
          title={event.hidden ? "Показать в плане" : "Не включать в план"}
          disabled={setHidden.isPending}
          onClick={() => setHidden.mutate(!event.hidden, { onError: toastError("Не удалось изменить событие") })}
          className="touch-target flex shrink-0 items-center justify-center text-text-3 hover:text-accent disabled:opacity-50"
        >
          {event.hidden ? <Eye className="size-4" /> : <EyeOff className="size-4" />}
        </button>
      ) : (
        <>
          <EditButton name={event.title} onClick={() => onEdit(event)} />
          <ConfirmDeleteButton
            kind="событие"
            name={event.title}
            pending={deleteEvent.isPending}
            onConfirm={() => deleteEvent.mutate(event.id, { onError: toastError("Не удалось удалить") })}
          />
        </>
      )}
    </li>
  );
}
