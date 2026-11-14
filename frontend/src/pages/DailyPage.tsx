import { PageHeader } from "@/components/layout/PageHeader";
import { PageTabs, type PageTab } from "@/components/common/navigation/PageTabs";
import { QueryState } from "@/components/common/feedback/QueryState";
import { DailyPlansTab } from "@/components/daily/DailyPlansTab";
import { DailyTemplateTab } from "@/components/daily/DailyTemplateTab";
import { DayHistoryTab } from "@/components/daily/DayHistoryTab";
import { useDailyCalendar } from "@/hooks/useDaily";
import type { DailyCalendar } from "@/lib/daily.types";
import { PAGE_BODY, PAGE_ROOT } from "@/styles/classes";

function dailyTabs(calendar: DailyCalendar): PageTab[] {
  return [
    { value: "history", label: "История", content: <DayHistoryTab calendar={calendar} /> },
    { value: "plans", label: "Планы на день", content: <DailyPlansTab calendar={calendar} /> },
    { value: "templates", label: "Шаблоны", content: <DailyTemplateTab /> },
  ];
}

/** Раздел 15.8: «Дейли» — отметки задач по дням, события и планы на день. */
export function DailyPage() {
  const { data: calendar, isLoading, isError } = useDailyCalendar();

  return (
    <div className={PAGE_ROOT}>
      <PageHeader title="Дейли" />
      <div className={PAGE_BODY}>
        <QueryState isLoading={isLoading} isError={isError} errorLabel="Не удалось загрузить дни">
          {calendar && <PageTabs tabs={dailyTabs(calendar)} />}
        </QueryState>
      </div>
    </div>
  );
}
