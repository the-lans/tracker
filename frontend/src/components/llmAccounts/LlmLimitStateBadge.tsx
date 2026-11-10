import { Badge } from "@/components/ui/badge";
import { LLM_LIMIT_STATE_LABEL, LLM_LIMIT_STATE_TONE } from "@/lib/labels";
import { LlmLimitState, type LlmAccount } from "@/lib/types";
import { formatResetTime, plural } from "@/lib/utils";

const TASK_FORMS: [string, string, string] = ["задача", "задачи", "задач"];

function details(account: LlmAccount): string[] {
  const parts: string[] = [];
  const until = account.limit_state_until;
  if (until) {
    const prefix = account.limit_state === LlmLimitState.RUNNING ? "окно до" : "до";
    parts.push(`${prefix} ${formatResetTime(until)}`);
  }
  if (account.active_tasks > 0) {
    parts.push(`${account.active_tasks} ${plural(account.active_tasks, TASK_FORMS)}`);
  }
  return parts;
}

/**
 * Раздел 15.1, 19.7: состояние лимита аккаунта — «Запущен · окно до 18:40 ·
 * 2 задачи», «Свободен», «На пороге до 18:40», «Исчерпан до 14 нояб.».
 * У аккаунта, который не участвует в выборе, бейджа нет: это видно по статусу.
 */
export function LlmLimitStateBadge({ account }: { account: LlmAccount }) {
  if (account.limit_state === LlmLimitState.EXCLUDED) return null;
  const text = [LLM_LIMIT_STATE_LABEL[account.limit_state], ...details(account)].join(" · ");
  return <Badge tone={LLM_LIMIT_STATE_TONE[account.limit_state]}>{text}</Badge>;
}
