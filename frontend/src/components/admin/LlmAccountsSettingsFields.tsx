import { IntegerSettingField } from "@/components/common/inputs/IntegerSettingField";
import type { ParsedInteger } from "@/lib/integerInput";
import {
  MAX_LLM_COMPACT_MIN_CONTEXT_CHARS,
  MAX_LLM_THRESHOLD_PCT,
  MIN_LLM_THRESHOLD_PCT,
} from "@/lib/types";

interface IntegerDraft {
  draft: string;
  parsed: ParsedInteger;
  onChange: (draft: string) => void;
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
      <IntegerSettingField
        id="llm_switch_threshold_week_pct"
        label="Порог недельного лимита, %"
        min={MIN_LLM_THRESHOLD_PCT}
        max={MAX_LLM_THRESHOLD_PCT}
        hint="Когда недельный расход аккаунта доходит до порога, задача переходит на другой аккаунт; если у всех аккаунтов автора порог достигнут, задача ждёт сброса недели. Порог общий для всех пользователей и аккаунтов; порог 5-часового окна каждый задаёт в профиле."
        {...week}
      />
      <IntegerSettingField
        id="llm_compact_min_context_chars"
        label="Минимум контекста для сжатия, симв."
        min={0}
        max={MAX_LLM_COMPACT_MIN_CONTEXT_CHARS}
        inputClassName="w-40"
        hint="При смене аккаунта контекст короче этого (символов в промтах и ответах текущей сессии) не сжимается: у новой сессии и совсем короткой переписки сжимать нечего. 0 — сжимать при любой истории. Действует, если у пользователя включено «Сжимать контекст при смене LLM-аккаунта»."
        {...compact}
      />
    </fieldset>
  );
}
