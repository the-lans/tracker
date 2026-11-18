import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { ParsedInteger } from "@/lib/integerInput";

/**
 * Целочисленная настройка формы: подпись, поле и подсказка под ним (раздел 15.5).
 * ``parsed`` — результат `parseIntegerInRange` по черновику ``draft``; неверное
 * значение подсвечивается и заменяет ``hint`` текстом о допустимых границах.
 */
export function IntegerSettingField({
  id,
  label,
  draft,
  parsed,
  min,
  max,
  hint,
  invalidHint = `Целое число от ${min} до ${max}`,
  inputClassName = "w-32",
  onChange,
}: {
  id: string;
  label: string;
  draft: string;
  parsed: ParsedInteger;
  min: number;
  max: number;
  hint: string;
  invalidHint?: string;
  inputClassName?: string;
  onChange: (draft: string) => void;
}) {
  return (
    <>
      <div>
        <Label htmlFor={id}>{label}</Label>
        <Input
          id={id}
          type="number"
          inputMode="numeric"
          className={inputClassName}
          min={min}
          max={max}
          value={draft}
          aria-invalid={!parsed.valid}
          onChange={(event) => onChange(event.target.value)}
          required
        />
      </div>
      <div className={parsed.valid ? "text-small text-text-3" : "text-small text-danger-text"}>
        {parsed.valid ? hint : invalidHint}
      </div>
    </>
  );
}
