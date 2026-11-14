import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { ParsedInteger } from "@/lib/integerInput";
import { MAX_RETENTION_DAYS, RETENTION_FOREVER } from "@/lib/types";

const FIELD_ID = "app_logs_retention_days";

function hintOf(parsed: ParsedInteger): string {
  if (!parsed.valid) return `Целое число от ${RETENTION_FOREVER} до ${MAX_RETENTION_DAYS}`;
  if (parsed.value === RETENTION_FOREVER) return "Журнал хранится бессрочно.";
  return "Записи журнала старше срока удаляются раз в день; 0 — хранить бессрочно.";
}

/** Раздел 17.2: срок хранения журнала приложения в «Системных настройках». */
export function AppLogsRetentionField({
  draft,
  parsed,
  onChange,
}: {
  draft: string;
  parsed: ParsedInteger;
  onChange: (draft: string) => void;
}) {
  return (
    <fieldset className="mt-1 flex flex-col gap-2 border-t border-border pt-3">
      <legend className="text-body font-bold text-text">Хранение данных</legend>
      <div>
        <Label htmlFor={FIELD_ID}>Журнал приложения, дн.</Label>
        <Input
          id={FIELD_ID}
          type="number"
          inputMode="numeric"
          className="w-32"
          min={RETENTION_FOREVER}
          max={MAX_RETENTION_DAYS}
          value={draft}
          aria-invalid={!parsed.valid}
          onChange={(event) => onChange(event.target.value)}
          required
        />
      </div>
      <div className={parsed.valid ? "text-small text-text-3" : "text-small text-danger-text"}>
        {hintOf(parsed)}
      </div>
    </fieldset>
  );
}
