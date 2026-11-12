import { Badge } from "@/components/ui/badge";
import { LlmUsageMeter } from "@/components/llmAccounts/LlmUsageMeter";
import { MonitoringCard } from "@/components/monitoring/MonitoringCard";
import { useLlmUsage } from "@/hooks/useMonitoring";
import { LLM_ACCOUNT_STATUS_LABEL, LLM_ACCOUNT_STATUS_TONE } from "@/lib/labels";
import type { AccountUsage } from "@/lib/monitoring.types";
import { formatRelativeShort } from "@/lib/utils";

function AccountUsageRow({ account }: { account: AccountUsage }) {
  return (
    <li className="flex min-w-0 flex-col gap-2 border-t border-border pt-3 first:border-t-0 first:pt-0">
      <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
        <span className="min-w-0 truncate font-bold text-text" title={account.label}>
          {account.label}
        </span>
        <Badge tone={LLM_ACCOUNT_STATUS_TONE[account.status]}>
          {LLM_ACCOUNT_STATUS_LABEL[account.status]}
        </Badge>
        <span className="min-w-0 truncate text-small text-text-3" title={account.owner_email}>
          {account.owner_email}
        </span>
      </div>
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        <LlmUsageMeter label="5 часов" pct={account.usage_5h_pct} resetsAt={account.usage_5h_resets_at} />
        <LlmUsageMeter label="Неделя" pct={account.usage_week_pct} resetsAt={account.usage_week_resets_at} />
      </div>
      <div className="text-caption text-text-3">
        Опрос: {formatRelativeShort(account.usage_checked_at)} · переключений на аккаунт за сутки:{" "}
        {account.switches_to_24h}
      </div>
    </li>
  );
}

/** Раздел 15.5, 19.7: расход окон лимита LLM-аккаунтов и автоматические переключения за сутки. */
export function LlmUsageCard() {
  const { data, isLoading, isError } = useLlmUsage();

  return (
    <MonitoringCard
      title="Расход LLM"
      isLoading={isLoading}
      isError={isError}
      action={
        data && (
          <span className="text-small font-bold text-text-3">
            Переключений за сутки: <span className="tabular-nums text-text">{data.switches_24h}</span>
          </span>
        )
      }
    >
      {data && data.accounts.length === 0 && (
        <div className="text-body text-text-3">LLM-аккаунтов пока нет</div>
      )}
      {data && data.accounts.length > 0 && (
        <ul className="flex flex-col gap-3">
          {data.accounts.map((account) => (
            <AccountUsageRow key={account.id} account={account} />
          ))}
        </ul>
      )}
    </MonitoringCard>
  );
}
