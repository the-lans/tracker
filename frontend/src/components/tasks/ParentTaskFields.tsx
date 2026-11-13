import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { SearchSelect } from "@/components/common/inputs/SearchSelect";
import { useTasks } from "@/hooks/useTasks";

/** Раздел 3.1: родительская задача и флажок «передать саммари родителя» —
 * пересказ истории родителя станет первым сообщением сессии этой задачи. */
export function ParentTaskFields({
  parentTaskId,
  useParentSummary,
  onChange,
}: {
  parentTaskId: string;
  useParentSummary: boolean;
  onChange: (patch: { parentTaskId?: string; useParentSummary?: boolean }) => void;
}) {
  // Раздел 3.1: родителем может быть и задача из архива.
  const { data: tasks } = useTasks(undefined, { includeArchived: true });

  const options = (tasks ?? []).map((task) => ({ value: task.id, label: `${task.code} · ${task.title}` }));

  function selectParent(value: string | null) {
    const nextParent = value ?? "";
    onChange({ parentTaskId: nextParent, useParentSummary: nextParent ? useParentSummary : false });
  }

  return (
    <div className="flex flex-col gap-2">
      <div>
        <Label htmlFor="task-parent">Родительская задача</Label>
        <SearchSelect
          id="task-parent"
          value={parentTaskId || null}
          options={options}
          onChange={selectParent}
          clearLabel="Без родителя"
          placeholder="Код или название задачи"
        />
      </div>
      <label className="flex items-center gap-2 text-note text-text-2">
        <Checkbox
          checked={useParentSummary}
          disabled={!parentTaskId}
          onCheckedChange={(checked) => onChange({ useParentSummary: checked === true })}
        />
        Передать саммари родителя первым сообщением сессии
      </label>
    </div>
  );
}
