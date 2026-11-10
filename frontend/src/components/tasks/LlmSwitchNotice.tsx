import { ArrowRightLeft } from "lucide-react";
import { LLM_SWITCH_REASON_LABEL } from "@/lib/labels";
import type { LlmSwitchReason } from "@/lib/types";

/**
 * Раздел 15.2: служебная строка перед ответом, если аккаунт сменился; перед
 * сменой сессия могла сжать контекст (`/compact`, раздел 19.7).
 */
export function LlmSwitchNotice({
  accountLabel,
  model,
  reason,
  compacted,
}: {
  accountLabel: string;
  model: string | null;
  reason: LlmSwitchReason;
  compacted: boolean;
}) {
  const target = model ? `${accountLabel} (${model})` : accountLabel;
  return (
    <div
      role="note"
      className="flex items-center justify-center gap-1.5 text-center text-caption text-text-3"
    >
      <ArrowRightLeft className="size-3 shrink-0" />
      <span>
        Переключено на аккаунт {target}: {LLM_SWITCH_REASON_LABEL[reason]}
        {compacted && " · контекст сессии сжат перед сменой"}
      </span>
    </div>
  );
}
