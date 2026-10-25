import { Checkbox } from "@/components/ui/checkbox";

/** Раздел 3.2: архивные записи скрыты по умолчанию и показываются по флажку. */
export function ShowArchivedToggle({
  checked,
  onChange,
}: {
  checked: boolean;
  onChange: (checked: boolean) => void;
}) {
  return (
    <label className="flex min-h-11 items-center gap-2.5 text-note text-text-2">
      <Checkbox checked={checked} onCheckedChange={(value) => onChange(value === true)} />
      Показать архивные
    </label>
  );
}
