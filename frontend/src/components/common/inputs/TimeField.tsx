import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

/** Поле времени «ЧЧ:ММ» с подписью; значение — как в поле `type="time"`. */
export function TimeField({
  id,
  label,
  value,
  onChange,
  required = false,
  invalid = false,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  required?: boolean;
  invalid?: boolean;
}) {
  return (
    <div>
      <Label htmlFor={id}>{label}</Label>
      <Input
        id={id}
        type="time"
        className="w-32"
        value={value}
        aria-invalid={invalid || undefined}
        onChange={(event) => onChange(event.target.value)}
        required={required}
      />
    </div>
  );
}
