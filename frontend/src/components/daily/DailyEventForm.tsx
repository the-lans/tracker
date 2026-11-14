import { useState } from "react";
import { Button } from "@/components/ui/button";
import { DialogFooter } from "@/components/ui/dialog";
import { Input, Textarea } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { TimeField } from "@/components/common/inputs/TimeField";
import { useCreateDailyEvent, useUpdateDailyEvent } from "@/hooks/useDaily";
import type { DailyCalendar, DailyEvent, DailyEventRequest } from "@/lib/daily.types";
import { optionalApiClockTime, optionalClockTime } from "@/lib/clockTime";
import { toastError } from "@/lib/errors";

/** Лимиты `DailyEventRequest` (`api/schemas/daily.py`). */
const MAX_TITLE_LENGTH = 200;
const MAX_NOTES_LENGTH = 2000;

/**
 * Раздел 15.8: ручное событие дня. Без времени — событие на весь день;
 * время по Москве, событие после полуночи до начала дня — ночь этого же дня.
 */
export function DailyEventForm({
  calendar,
  day,
  event,
  onSaved,
  onCancel,
}: {
  calendar: DailyCalendar;
  day: string;
  event?: DailyEvent;
  onSaved: () => void;
  onCancel: () => void;
}) {
  const createEvent = useCreateDailyEvent();
  const updateEvent = useUpdateDailyEvent(event?.id ?? "");
  const [eventDay, setEventDay] = useState(event?.day ?? day);
  const [title, setTitle] = useState(event?.title ?? "");
  const [notes, setNotes] = useState(event?.notes ?? "");
  const [start, setStart] = useState(optionalClockTime(event?.start_time));
  const [end, setEnd] = useState(optionalClockTime(event?.end_time));
  const isPending = createEvent.isPending || updateEvent.isPending;
  const oldestDay = calendar.history_days[calendar.history_days.length - 1];
  const endWithoutStart = Boolean(end) && !start;

  function handleSave() {
    const body: DailyEventRequest = {
      day: eventDay,
      title: title.trim(),
      notes: notes.trim() || null,
      start_time: optionalApiClockTime(start),
      end_time: optionalApiClockTime(end),
    };
    const options = { onSuccess: onSaved, onError: toastError("Не удалось сохранить событие") };
    if (event) updateEvent.mutate(body, options);
    else createEvent.mutate(body, options);
  }

  return (
    <>
      <div className="flex flex-col gap-3">
        <div>
          <Label htmlFor="daily-event-title">Название</Label>
          <Input
            id="daily-event-title"
            value={title}
            maxLength={MAX_TITLE_LENGTH}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Ревью кода, созвон, выкатка релиза"
          />
        </div>
        <div className="flex flex-wrap gap-3">
          <div>
            <Label htmlFor="daily-event-day">День</Label>
            <Input
              id="daily-event-day"
              type="date"
              className="w-44"
              min={oldestDay}
              max={calendar.tomorrow}
              value={eventDay}
              onChange={(e) => setEventDay(e.target.value)}
            />
          </div>
          <TimeField id="daily-event-start" label="Начало, МСК" value={start} onChange={setStart} />
          <TimeField
            id="daily-event-end"
            label="Конец, МСК"
            value={end}
            onChange={setEnd}
            invalid={endWithoutStart}
          />
        </div>
        <div className="text-small text-text-3">
          {endWithoutStart
            ? "Укажите начало события или очистите конец"
            : "Без времени событие — на весь день."}
        </div>
        <div>
          <Label htmlFor="daily-event-notes">Заметка</Label>
          <Textarea
            id="daily-event-notes"
            rows={3}
            maxLength={MAX_NOTES_LENGTH}
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
          />
        </div>
      </div>
      <DialogFooter>
        <Button variant="secondary" onClick={onCancel}>
          Отмена
        </Button>
        <Button onClick={handleSave} disabled={!title.trim() || !eventDay || endWithoutStart || isPending}>
          {event ? "Сохранить" : "Добавить"}
        </Button>
      </DialogFooter>
    </>
  );
}
