import { cn } from "@/lib/utils";

export type WorkspaceView = "dialogue" | "logs";

const VIEWS: Array<{ value: WorkspaceView; label: string }> = [
  { value: "dialogue", label: "Выполнение" },
  { value: "logs", label: "Логи" },
];

/**
 * Раздел 13.4, 15.2: переключатель правой панели страницы задачи. Только на
 * широком экране — на узком те же разделы есть во вкладках верхнего уровня.
 */
export function TaskWorkspaceTabs({
  value,
  onChange,
}: {
  value: WorkspaceView;
  onChange: (value: WorkspaceView) => void;
}) {
  return (
    <div className="hidden gap-4 xl:flex" role="tablist">
      {VIEWS.map((view) => (
        <button
          key={view.value}
          type="button"
          role="tab"
          aria-selected={value === view.value}
          onClick={() => onChange(view.value)}
          className={cn(
            "touch-hit text-caption font-extrabold uppercase tracking-wider text-text-3",
            value === view.value && "text-accent",
          )}
        >
          {view.label}
        </button>
      ))}
    </div>
  );
}
