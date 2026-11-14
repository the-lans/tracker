import { useState } from "react";
import { ClipboardList, Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { EmptyState } from "@/components/common/feedback/EmptyState";
import { QueryState } from "@/components/common/feedback/QueryState";
import { DailyPlanEditor } from "@/components/daily/DailyPlanEditor";
import { useCreateDailyPlan, useDailyPlans } from "@/hooks/useDaily";
import type { DailyCalendar } from "@/lib/daily.types";
import { formatDay, fullDayLabel, relativeDayName } from "@/lib/dailyDays";
import { toastError } from "@/lib/errors";
import { cn } from "@/lib/utils";

/** Раздел 15.8: «Планы на день» — один план на день, собирается по шаблону и правится. */
export function DailyPlansTab({ calendar }: { calendar: DailyCalendar }) {
  const { data: plans, isLoading, isError } = useDailyPlans();
  const createPlan = useCreateDailyPlan();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const plannedDays = new Set((plans ?? []).map((plan) => plan.day));
  const freeDays = calendar.history_days.filter((day) => !plannedDays.has(day));
  const [newDay, setNewDay] = useState(calendar.today);
  const dayToCreate = freeDays.includes(newDay) ? newDay : freeDays[0];
  const selected = (plans ?? []).find((plan) => plan.id === selectedId) ?? plans?.[0];

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <Select value={dayToCreate ?? ""} onValueChange={setNewDay} disabled={freeDays.length === 0}>
          <SelectTrigger className="w-48" aria-label="День нового плана">
            <SelectValue placeholder="Все дни уже с планом" />
          </SelectTrigger>
          <SelectContent>
            {freeDays.map((day) => (
              <SelectItem key={day} value={day}>
                {fullDayLabel(day, calendar)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Button
          disabled={!dayToCreate || createPlan.isPending}
          onClick={() =>
            dayToCreate &&
            createPlan.mutate(dayToCreate, {
              onSuccess: (plan) => setSelectedId(plan.id),
              onError: toastError("Не удалось создать план"),
            })}
        >
          <Plus className="size-4" /> Новый план
        </Button>
      </div>
      <QueryState isLoading={isLoading} isError={isError} errorLabel="Не удалось загрузить планы">
        {!selected ? (
          <EmptyState
            icon={ClipboardList}
            title="Планов пока нет"
            hint="План собирается по шаблону из вкладки «Шаблоны»: что сделано в прошлый день и что запланировано на выбранный. Текст можно поправить и скопировать."
          />
        ) : (
          <div className="grid grid-cols-1 gap-3 lg:grid-cols-[16rem_minmax(0,1fr)]">
            <Card className="p-2">
              <ul aria-label="Планы" className="flex flex-col gap-0.5">
                {(plans ?? []).map((plan) => (
                  <li key={plan.id}>
                    <button
                      type="button"
                      aria-current={plan.id === selected.id}
                      onClick={() => setSelectedId(plan.id)}
                      className={cn(
                        "touch-target w-full rounded-md px-2 py-1.5 text-left hover:bg-surface-2",
                        plan.id === selected.id && "bg-accent-tint text-accent-hov",
                      )}
                    >
                      <span className="font-bold">{formatDay(plan.day)}</span>{" "}
                      <span className="text-small text-text-3">{relativeDayName(plan.day, calendar)}</span>
                    </button>
                  </li>
                ))}
              </ul>
            </Card>
            <DailyPlanEditor
              key={`${selected.id}:${selected.updated_at}`}
              plan={selected}
              calendar={calendar}
              onDeleted={() => setSelectedId(null)}
            />
          </div>
        )}
      </QueryState>
    </div>
  );
}
