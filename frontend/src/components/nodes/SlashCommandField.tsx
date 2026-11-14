import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

/** Имя нативной команды буквально; настроенные аргументы могут содержать поля задачи. */
export function SlashCommandField({
  value,
  onChange,
}: {
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <div>
      <Label htmlFor="node-command" required>Слэш-команда</Label>
      <Input
        id="node-command"
        placeholder="/code-review ultra"
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
      <p className="mt-1 text-caption text-text-3">
        {"В аргументах можно использовать поля задачи, например /review {{task.code}}. Имя команды остаётся буквальным."}
      </p>
    </div>
  );
}
