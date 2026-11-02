import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { REASONING_EFFORT_LABEL } from "@/lib/labels";
import { ReasoningEffort } from "@/lib/types";

// Radix Select не принимает пустое значение — «по умолчанию аккаунта» кодируется так.
const ACCOUNT_DEFAULT = "account_default";

/**
 * Уровень рассуждений по шкале трекера (раздел 19.7). С `allowDefault`
 * доступен пункт «По умолчанию аккаунта» — `null` (нода, раздел 11.1).
 */
export function ReasoningEffortSelect({
  id,
  value,
  onChange,
  allowDefault = false,
}: {
  id: string;
  value: ReasoningEffort | null;
  onChange: (value: ReasoningEffort | null) => void;
  allowDefault?: boolean;
}) {
  return (
    <Select
      value={value ?? ACCOUNT_DEFAULT}
      onValueChange={(next) => onChange(next === ACCOUNT_DEFAULT ? null : (next as ReasoningEffort))}
    >
      <SelectTrigger id={id}>
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {allowDefault && <SelectItem value={ACCOUNT_DEFAULT}>По умолчанию аккаунта</SelectItem>}
        {Object.values(ReasoningEffort).map((effort) => (
          <SelectItem key={effort} value={effort}>
            {REASONING_EFFORT_LABEL[effort]}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
