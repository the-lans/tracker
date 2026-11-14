import { ToggleChip } from "@/components/common/actions/ToggleChip";
import { useDailyCalendar, useDayMarks, useToggleDayMark } from "@/hooks/useDaily";
import { toastError } from "@/lib/errors";
import { MARK_DAY_LABEL } from "@/lib/dailyDays";
import { TaskStatus, type Task } from "@/lib/types";

const MARKABLE_DAYS = ["today", "tomorrow"] as const;

/**
 * Раздел 15.8: отметка задачи «Сегодня» / «Завтра» — только намерение, задачу
 * она не запускает и на следующий день не переносится. Отметки личные;
 * архивную задачу отметить нельзя.
 */
export function TaskDayMarks({ task }: { task: Task }) {
  const { data: calendar } = useDailyCalendar();
  const { data: marks } = useDayMarks();
  const toggle = useToggleDayMark(task.id);
  if (!calendar || task.status === TaskStatus.ARCHIVED) return null;
  const marked = marks?.get(task.id);

  return (
    <div className="flex items-center gap-1.5" role="group" aria-label="Отметить на день">
      {MARKABLE_DAYS.map((key) => {
        const day = calendar[key];
        const pressed = marked?.has(day) ?? false;
        return (
          <ToggleChip
            key={key}
            size="sm"
            pressed={pressed}
            disabled={toggle.isPending}
            title={pressed ? "Снять отметку" : "Запланировать на этот день"}
            onToggle={() =>
              toggle.mutate({ day, marked: !pressed }, { onError: toastError("Не удалось изменить отметку") })}
          >
            {MARK_DAY_LABEL[key]}
          </ToggleChip>
        );
      })}
    </div>
  );
}
