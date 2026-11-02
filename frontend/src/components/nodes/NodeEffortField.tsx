import { ReasoningEffortSelect } from "@/components/llmAccounts/ReasoningEffortSelect";
import { Label } from "@/components/ui/label";
import type { ReasoningEffort } from "@/lib/types";

/** Раздел 15.4: уровень рассуждений LLM-ноды; `null` — уровень аккаунта по умолчанию. */
export function NodeEffortField({
  id,
  value,
  onChange,
}: {
  id: string;
  value: ReasoningEffort | null;
  onChange: (value: ReasoningEffort | null) => void;
}) {
  return (
    <div>
      <Label htmlFor={id}>Уровень рассуждений</Label>
      <ReasoningEffortSelect id={id} value={value} onChange={onChange} allowDefault />
      <p className="mt-1 text-meta text-text-3">
        Применяется к модели того аккаунта, на котором нода выполнится, и переводится на шкалу его
        провайдера.
      </p>
    </div>
  );
}
