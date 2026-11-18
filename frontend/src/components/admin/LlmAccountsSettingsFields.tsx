import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { ParsedInteger } from "@/lib/integerInput";
import {
  MAX_LLM_COMPACT_MIN_CONTEXT_CHARS,
  MAX_LLM_THRESHOLD_PCT,
  MIN_LLM_THRESHOLD_PCT,
} from "@/lib/types";

const WEEK_FIELD_ID = "llm_switch_threshold_week_pct";
const COMPACT_FIELD_ID = "llm_compact_min_context_chars";

interface IntegerDraft {
  draft: string;
  parsed: ParsedInteger;
  onChange: (draft: string) => void;
}

function Hint({ parsed, valid, invalid }: { parsed: ParsedInteger; valid: string; invalid: string }) {
  return (
    <div className={parsed.valid ? "text-small text-text-3" : "text-small text-danger-text"}>
      {parsed.valid ? valid : invalid}
    </div>
  );
}

/**
 * Раздел 19.7: общие настройки LLM-аккаунтов в «Системных настройках» — порог
 * недельного расхода и минимум контекста для сжатия при смене аккаунта.
 */
export function LlmAccountsSettingsFields({
  week,
  compact,
}: {
  week: IntegerDraft;
  compact: IntegerDraft;
}) {
  return (
    <fieldset className="mt-1 flex flex-col gap-2 border-t border-border pt-3">
      <legend className="text-body font-bold text-text">LLM-аккаунты</legend>
      <div>
        <Label htmlFor={WEEK_FIELD_ID}>Порог недельного лимита, %</Label>
        <Input
          id={WEEK_FIELD_ID}
          type="number"
          inputMode="numeric"
          className="w-32"
          min={MIN_LLM_THRESHOLD_PCT}
          max={MAX_LLM_THRESHOLD_PCT}
          value={week.draft}
          aria-invalid={!week.parsed.valid}
          onChange={(event) => week.onChange(event.target.value)}
          required
        />
      </div>
      <Hint
        parsed={week.parsed}
        invalid={`Целое число от ${MIN_LLM_THRESHOLD_PCT} до ${MAX_LLM_THRESHOLD_PCT}`}
        valid="Когда недельный расход аккаунта доходит до порога, задача переходит на другой аккаунт; если у всех аккаунтов автора порог достигнут, задача ждёт сброса недели. Порог общий для всех пользователей и аккаунтов; порог 5-часового окна каждый задаёт в профиле."
      />
      <div>
        <Label htmlFor={COMPACT_FIELD_ID}>Минимум контекста для сжатия, симв.</Label>
        <Input
          id={COMPACT_FIELD_ID}
          type="number"
          inputMode="numeric"
          className="w-40"
          min={0}
          max={MAX_LLM_COMPACT_MIN_CONTEXT_CHARS}
          value={compact.draft}
          aria-invalid={!compact.parsed.valid}
          onChange={(event) => compact.onChange(event.target.value)}
          required
        />
      </div>
      <Hint
        parsed={compact.parsed}
        invalid={`Целое число от 0 до ${MAX_LLM_COMPACT_MIN_CONTEXT_CHARS}`}
        valid="При смене аккаунта контекст короче этого (символов в промтах и ответах текущей сессии) не сжимается: у новой сессии и совсем короткой переписки сжимать нечего. 0 — сжимать при любой истории. Действует, если у пользователя включено «Сжимать контекст при смене LLM-аккаунта»."
      />
    </fieldset>
  );
}
