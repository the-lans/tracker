import { Switch } from "@/components/ui/switch";

/** Раздел 9.4: переключатель «Принять план автоматически» — у задачи и у категории. */
export function AutoAcceptPlanField({
  checked,
  disabled,
  onCheckedChange,
}: {
  checked: boolean;
  disabled?: boolean;
  onCheckedChange: (checked: boolean) => void;
}) {
  return (
    <label className="flex items-center justify-between gap-3 py-1">
      <span>
        <span className="block text-body font-bold">Принять план автоматически</span>
        <span className="mt-0.5 block text-meta text-text-3">Без остановки на ревью плана</span>
      </span>
      <Switch checked={checked} disabled={disabled} onCheckedChange={onCheckedChange} />
    </label>
  );
}
