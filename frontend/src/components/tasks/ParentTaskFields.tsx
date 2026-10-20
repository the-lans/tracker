import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useTasks } from "@/hooks/useTasks";

const NO_PARENT = "none";

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
  const { data: tasks } = useTasks();

  function selectParent(value: string) {
    const nextParent = value === NO_PARENT ? "" : value;
    onChange({ parentTaskId: nextParent, useParentSummary: nextParent ? useParentSummary : false });
  }

  return (
    <div className="flex flex-col gap-2">
      <div>
        <Label>Родительская задача</Label>
        <Select value={parentTaskId || NO_PARENT} onValueChange={selectParent}>
          <SelectTrigger>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={NO_PARENT}>Без родителя</SelectItem>
            {(tasks ?? []).map((task) => (
              <SelectItem key={task.id} value={task.id}>
                {task.code} · {task.title}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      <label className="flex items-center gap-2 text-[12.5px] text-text-2">
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
