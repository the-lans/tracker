import { Cpu } from "lucide-react";
import { useLlmAccounts, useLlmProviders } from "@/hooks/useLlmAccounts";
import type { Task } from "@/lib/types";

function usagePart(label: string, pct: string | null): string | null {
  return pct === null ? null : `${label} ${Number(pct)}%`;
}

/**
 * Раздел 15.2: аккаунт, на котором сейчас работает сессия задачи, — пометка,
 * провайдер, модель и расход окон; до первого обращения — стартовый аккаунт.
 * После переключения обновляется событием канала задачи без перезагрузки.
 */
export function TaskLlmAccountBadge({ task }: { task: Task }) {
  const { data: accounts } = useLlmAccounts();
  const { data: providers } = useLlmProviders();
  const accountId = task.current_llm_account_id ?? task.llm_account_id;
  const account = accounts?.find((item) => item.id === accountId);
  if (!account) return null;
  const provider = providers?.find((item) => item.id === account.provider);
  const usage = [usagePart("5 ч", account.usage_5h_pct), usagePart("нед.", account.usage_week_pct)]
    .filter(Boolean)
    .join(" · ");

  return (
    <div
      aria-label="Текущий LLM-аккаунт"
      className="flex min-w-0 items-center gap-1.5 text-meta text-text-2"
      title={account.default_model ?? undefined}
    >
      <Cpu className="size-3.5 shrink-0 text-text-3" />
      <span className="truncate">
        <span className="font-bold text-text">{account.label}</span>
        {" · "}
        {provider?.label ?? account.provider}
        {account.default_model && ` · ${account.default_model}`}
        {usage && <span className="text-text-3"> · {usage}</span>}
      </span>
    </div>
  );
}
