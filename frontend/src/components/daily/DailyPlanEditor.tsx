import { useState } from "react";
import { Copy, RefreshCw } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Textarea } from "@/components/ui/input";
import { ConfirmDeleteButton } from "@/components/common/actions/ConfirmDeleteButton";
import { ConfirmActionButton } from "@/components/common/actions/ConfirmActionButton";
import { useDeleteDailyPlan, useRegenerateDailyPlan, useUpdateDailyPlan } from "@/hooks/useDaily";
import type { DailyCalendar, DailyPlan } from "@/lib/daily.types";
import { formatDay, relativeDayName } from "@/lib/dailyDays";
import { toastError } from "@/lib/errors";
import { copyText } from "@/lib/textExport";

/** Лимит `DailyPlanUpdateRequest` (`services/daily_plans.MAX_DAILY_TEXT_LENGTH`). */
const MAX_PLAN_LENGTH = 20000;

/**
 * План на день: текст собран по шаблону и правится вручную. «Пересобрать»
 * заменяет текст заново собранным по текущему шаблону — правки теряются.
 */
export function DailyPlanEditor({
  plan,
  calendar,
  onDeleted,
}: {
  plan: DailyPlan;
  calendar: DailyCalendar;
  onDeleted: () => void;
}) {
  const [draft, setDraft] = useState(plan.content);
  const updatePlan = useUpdateDailyPlan(plan.id);
  const regeneratePlan = useRegenerateDailyPlan(plan.id);
  const deletePlan = useDeleteDailyPlan();
  const title = `План на ${formatDay(plan.day)}`;
  const dayName = relativeDayName(plan.day, calendar);
  const changed = draft !== plan.content;

  function regenerate() {
    regeneratePlan.mutate(undefined, {
      onSuccess: (fresh) => setDraft(fresh.content),
      onError: toastError("Не удалось пересобрать план"),
    });
  }

  return (
    <Card className="flex min-w-0 flex-col gap-3">
      <div className="flex items-center gap-2">
        <div className="min-w-0 flex-1">
          <div className="font-bold">{title}</div>
          {dayName && <div className="text-small text-text-3">{dayName}</div>}
        </div>
        <ConfirmDeleteButton
          kind="план"
          name={title}
          pending={deletePlan.isPending}
          onConfirm={() =>
            deletePlan.mutate(plan.id, { onSuccess: onDeleted, onError: toastError("Не удалось удалить") })}
        />
      </div>
      <Textarea
        aria-label="Текст плана"
        rows={16}
        maxLength={MAX_PLAN_LENGTH}
        className="font-mono text-small"
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
      />
      <div className="flex flex-wrap gap-2">
        <Button
          disabled={!changed || updatePlan.isPending}
          onClick={() =>
            updatePlan.mutate(draft, {
              onSuccess: () => toast.success("План сохранён"),
              onError: toastError("Не удалось сохранить план"),
            })}
        >
          Сохранить
        </Button>
        <ConfirmActionButton
          title="Пересобрать план?"
          description="Текст плана заменится собранным по шаблону заново — ручные правки пропадут."
          confirmLabel="Пересобрать"
          pending={regeneratePlan.isPending}
          onConfirm={regenerate}
        >
          <RefreshCw className="size-4" /> Пересобрать по шаблону
        </ConfirmActionButton>
        <Button variant="secondary" onClick={() => copyText(draft)}>
          <Copy className="size-4" /> Копировать
        </Button>
      </div>
    </Card>
  );
}
