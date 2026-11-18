import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { ParsedInteger } from "@/lib/integerInput";
import { MAX_LLM_THRESHOLD_PCT, MIN_LLM_THRESHOLD_PCT } from "@/lib/types";

const FIELD_ID = "llm_switch_threshold_week_pct";

function hintOf(parsed: ParsedInteger): string {
  if (!parsed.valid) return `Целое число от ${MIN_LLM_THRESHOLD_PCT} до ${MAX_LLM_THRESHOLD_PCT}`;
  return "Когда недельный расход аккаунта доходит до порога, задача переходит на другой аккаунт; если у всех аккаунтов автора порог достигнут, задача ждёт сброса недели. Порог общий для всех пользователей и аккаунтов; порог 5-часового окна каждый задаёт в профиле.";
}

/** Раздел 19.7: порог недельного расхода LLM-аккаунтов в «Системных настройках». */
export function LlmWeekThresholdField({
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
      <legend className="text-body font-bold text-text">LLM-аккаунты</legend>
      <div>
        <Label htmlFor={FIELD_ID}>Порог недельного лимита, %</Label>
        <Input
          id={FIELD_ID}
          type="number"
          inputMode="numeric"
          className="w-32"
          min={MIN_LLM_THRESHOLD_PCT}
          max={MAX_LLM_THRESHOLD_PCT}
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
