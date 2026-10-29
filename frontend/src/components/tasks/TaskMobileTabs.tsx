import type { WorkspaceView } from "@/components/tasks/TaskWorkspaceTabs";
import { cn } from "@/lib/utils";

export type MobileTaskTab = "overview" | WorkspaceView;

const TABS: Array<{ value: MobileTaskTab; label: string }> = [
  { value: "overview", label: "Обзор" },
  { value: "dialogue", label: "Диалог" },
  { value: "logs", label: "Логи" },
];

/** Раздел 15.3: вкладки страницы задачи на узком экране. */
export function TaskMobileTabs({
  value,
  onChange,
}: {
  value: MobileTaskTab;
  onChange: (value: MobileTaskTab) => void;
}) {
  return (
    <div className="flex border-b border-border xl:hidden" role="tablist">
      {TABS.map((tab) => (
        <button
          key={tab.value}
          type="button"
          role="tab"
          aria-selected={value === tab.value}
          onClick={() => onChange(tab.value)}
          className={cn(
            "flex-1 touch-target border-b-2 border-transparent py-2.5 text-body font-bold text-text-2 short:py-1",
            value === tab.value && "border-accent text-accent",
          )}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
}
