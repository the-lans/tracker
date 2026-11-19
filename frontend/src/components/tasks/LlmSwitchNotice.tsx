import { ArrowRightLeft } from "lucide-react";
import { FeedNotice } from "@/components/tasks/FeedNotice";
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
    <FeedNotice icon={ArrowRightLeft}>
      Переключено на аккаунт {target}: {LLM_SWITCH_REASON_LABEL[reason]}
      {compacted && " · контекст сессии сжат перед сменой"}
    </FeedNotice>
  );
}
