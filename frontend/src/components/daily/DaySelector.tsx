import { SegmentedControl } from "@/components/common/navigation/SegmentedControl";
import type { DailyCalendar } from "@/lib/daily.types";
import { historyDayLabels } from "@/lib/dailyDays";

/** Раздел 15.8: день «Истории» — завтра, сегодня, вчера, позавчера и ещё 5 прошлых дней. */
export function DaySelector({
  calendar,
  value,
  onChange,
}: {
  calendar: DailyCalendar;
  value: string;
  onChange: (day: string) => void;
}) {
  return (
    <SegmentedControl
      value={value}
      options={historyDayLabels(calendar)}
      onChange={onChange}
      label="День"
      className="flex-wrap"
    />
  );
}
