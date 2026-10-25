import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

/** Правило 2: слэш-команда передаётся в сессию буквально. */
export function SlashCommandField({
  value,
  onChange,
}: {
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <div>
      <Label htmlFor="node-command">Слэш-команда</Label>
      <Input
        id="node-command"
        placeholder="/code-review ultra"
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
      <div className="mt-1 text-caption text-text-3">
        Команда передаётся в сессию без изменений — шаблонизатор не применяется.
      </div>
    </div>
  );
}
