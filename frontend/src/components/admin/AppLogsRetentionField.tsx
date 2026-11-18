import { IntegerSettingField } from "@/components/common/inputs/IntegerSettingField";
import type { ParsedInteger } from "@/lib/integerInput";
import { MAX_RETENTION_DAYS, RETENTION_FOREVER } from "@/lib/types";

function hintOf(parsed: ParsedInteger): string {
  if (parsed.valid && parsed.value === RETENTION_FOREVER) return "Журнал хранится бессрочно.";
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
      <IntegerSettingField
        id="app_logs_retention_days"
        label="Журнал приложения, дн."
        draft={draft}
        parsed={parsed}
        min={RETENTION_FOREVER}
        max={MAX_RETENTION_DAYS}
        hint={hintOf(parsed)}
        onChange={onChange}
      />
    </fieldset>
  );
}
