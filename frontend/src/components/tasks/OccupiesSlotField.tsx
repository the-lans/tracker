import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";

/** Раздел 14.4: галочка «Занимать слот параллельного запуска задач» — у задачи и у категории. */
export function OccupiesSlotField({
  id,
  checked,
  disabled,
  onCheckedChange,
}: {
  id: string;
  checked: boolean;
  disabled?: boolean;
  onCheckedChange: (checked: boolean) => void;
}) {
  return (
    <div className="flex items-start gap-3">
      <Checkbox
        id={id}
        className="mt-0.5"
        checked={checked}
        disabled={disabled}
        onCheckedChange={(state) => onCheckedChange(state === true)}
      />
      <div>
        <Label htmlFor={id} className="text-note font-bold">
          Занимать слот параллельного запуска задач
        </Label>
        <div className="mt-0.5 text-meta text-text-3">
          Для ручного запуска и чата в «Уточняется». Задача из очереди слот занимает всегда.
        </div>
      </div>
    </div>
  );
}
