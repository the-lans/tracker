import { useState } from "react";
import { Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardTitle } from "@/components/ui/card";
import { EntityFormDialog, type EditTarget } from "@/components/common/dialogs/EntityFormDialog";
import { EmptyState } from "@/components/common/feedback/EmptyState";
import { QueryState } from "@/components/common/feedback/QueryState";
import { DailyEventForm } from "@/components/daily/DailyEventForm";
import { DailyEventRow } from "@/components/daily/DailyEventRow";
import { DaySelector } from "@/components/daily/DaySelector";
import { DayTaskRow } from "@/components/daily/DayTaskRow";
import { useDailyDay } from "@/hooks/useDaily";
import type { DailyCalendar, DailyEvent } from "@/lib/daily.types";
import { clockTime } from "@/lib/clockTime";
import { fullDayLabel } from "@/lib/dailyDays";

/** Раздел 15.8: «История» — отмеченные задачи дня с итогом и события дня. */
export function DayHistoryTab({ calendar }: { calendar: DailyCalendar }) {
  const [day, setDay] = useState(calendar.today);
  const { data, isLoading, isError } = useDailyDay(day);
  const [dialogEvent, setDialogEvent] = useState<EditTarget<DailyEvent>>(null);

  return (
    <div className="flex flex-col gap-3">
      <DaySelector calendar={calendar} value={day} onChange={setDay} />
      <div className="text-small text-text-3">
        {fullDayLabel(day, calendar)} · день начинается в {clockTime(calendar.day_start_time)} МСК
      </div>
      <QueryState isLoading={isLoading} isError={isError} errorLabel="Не удалось загрузить день">
        <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
          <Card>
            <CardTitle>Задачи</CardTitle>
            {(data?.tasks ?? []).length === 0 ? (
              <EmptyState
                compact
                title="Задач на этот день не отмечено"
                hint="Отметки «Сегодня» и «Завтра» ставятся в карточке задачи на дашборде и на странице задачи."
              />
            ) : (
              <ul className="divide-y divide-border">
                {data?.tasks.map((task) => <DayTaskRow key={task.id} task={task} />)}
              </ul>
            )}
          </Card>
          <Card>
            <div className="mb-2.5 flex items-center gap-2">
              <CardTitle className="mb-0 flex-1">События</CardTitle>
              <Button size="sm" variant="secondary" onClick={() => setDialogEvent("new")}>
                <Plus className="size-4" /> Событие
              </Button>
            </div>
            {(data?.events ?? []).length === 0 ? (
              <EmptyState
                compact
                title="Событий нет"
                hint="Добавьте событие вручную или подключите Google Calendar в профиле."
              />
            ) : (
              <ul className="divide-y divide-border">
                {data?.events.map((event) => <DailyEventRow key={event.id} event={event} onEdit={setDialogEvent} />)}
              </ul>
            )}
          </Card>
        </div>
      </QueryState>

      <EntityFormDialog
        target={dialogEvent}
        onClose={() => setDialogEvent(null)}
        createTitle="Новое событие"
        editTitle="Редактировать событие"
        contentClassName="max-w-lg"
      >
        {(item, close) => (
          <DailyEventForm calendar={calendar} day={day} event={item} onSaved={close} onCancel={close} />
        )}
      </EntityFormDialog>
    </div>
  );
}
