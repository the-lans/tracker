import { LogIn, Power } from "lucide-react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { ConfirmDeleteButton } from "@/components/common/actions/ConfirmDeleteButton";
import { EditButton } from "@/components/common/actions/EditButton";
import { ReorderButton } from "@/components/common/actions/ReorderButton";
import { OwnerLabel } from "@/components/common/avatar/OwnerLabel";
import { LlmLimitStateBadge } from "@/components/llmAccounts/LlmLimitStateBadge";
import { LlmUsageMeter } from "@/components/llmAccounts/LlmUsageMeter";
import { useDeleteLlmAccount, useUpdateLlmAccount } from "@/hooks/useLlmAccounts";
import { errorMessage } from "@/lib/errors";
import {
  LLM_ACCOUNT_STATUS_LABEL,
  LLM_ACCOUNT_STATUS_TONE,
  REASONING_EFFORT_LABEL,
} from "@/lib/labels";
import { LlmAccountStatus, type LlmAccount, type LlmProvider, type User } from "@/lib/types";
import { formatDateTime, formatRelativeShort } from "@/lib/utils";

/**
 * Раздел 15.1: строка аккаунта в порядке переключения — провайдер, модель,
 * уровень, статус и состояние лимита, расход окон с временем сброса и
 * последним опросом; порог есть только у 5-часового окна (раздел 19.7).
 */
export function LlmAccountRow({
  account,
  provider,
  thresholds,
  onMoveUp,
  onMoveDown,
  onEdit,
  onLogin,
}: {
  account: LlmAccount;
  provider?: LlmProvider;
  thresholds?: Pick<User, "llm_switch_threshold_5h_pct">;
  onMoveUp?: () => void;
  onMoveDown?: () => void;
  onEdit: () => void;
  onLogin: () => void;
}) {
  const update = useUpdateLlmAccount(account.id);
  const deleteAccount = useDeleteLlmAccount();
  const disabled = account.status === LlmAccountStatus.DISABLED;
  const loginLabel = account.signed_in ? "Войти заново" : "Войти";
  const needsLogin = !account.signed_in || account.status === LlmAccountStatus.LOGIN_REQUIRED;

  function toggleEnabled() {
    update.mutate(
      { enabled: disabled },
      { onError: (error) => toast.error(errorMessage(error, "Не удалось изменить аккаунт")) },
    );
  }

  return (
    // Строка в одну линию — только на широком экране: уже бейджи состояния
    // наезжали бы на шкалы расхода, поэтому ниже xl шкалы и кнопки — под названием.
    <Card className="flex flex-col gap-3 xl:flex-row xl:items-center">
      <div className="flex min-w-0 flex-1 items-start gap-2 xl:items-center">
        <div className="flex shrink-0 flex-col">
          <ReorderButton name={account.label} direction="up" disabled={!onMoveUp} onMove={() => onMoveUp?.()} />
          <ReorderButton name={account.label} direction="down" disabled={!onMoveDown} onMove={() => onMoveDown?.()} />
        </div>
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="truncate font-bold" title={account.label}>
              {account.label}
            </span>
            <Badge tone={LLM_ACCOUNT_STATUS_TONE[account.status]}>
              {LLM_ACCOUNT_STATUS_LABEL[account.status]}
            </Badge>
            <LlmLimitStateBadge account={account} />
          </div>
          <div className="text-meta text-text-2">
            {provider?.label ?? account.provider} · {account.default_model ?? "модель не выбрана"} ·{" "}
            {REASONING_EFFORT_LABEL[account.default_effort]}
          </div>
          {account.status === LlmAccountStatus.RATE_LIMITED && account.rate_limit_resets_at && (
            <div className="text-meta text-warning-text">
              Лимит до {formatDateTime(account.rate_limit_resets_at)}
            </div>
          )}
          <OwnerLabel ownerId={account.created_by} />
        </div>
      </div>
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between xl:shrink-0">
        {provider?.reports_usage !== false && account.signed_in && (
          <div className="grid grid-cols-2 gap-3 sm:w-72">
            <LlmUsageMeter
              label="5 часов"
              pct={account.usage_5h_pct}
              resetsAt={account.usage_5h_resets_at}
              threshold={thresholds?.llm_switch_threshold_5h_pct}
            />
            <LlmUsageMeter
              label="Неделя"
              pct={account.usage_week_pct}
              resetsAt={account.usage_week_resets_at}
            />
            <span className="col-span-2 text-caption text-text-3">
              опрос: {formatRelativeShort(account.usage_checked_at)}
            </span>
          </div>
        )}
        <div className="flex flex-wrap items-center gap-1">
          {needsLogin && (
            <Button size="sm" onClick={onLogin}>
              <LogIn className="size-4" /> {loginLabel}
            </Button>
          )}
          <Button size="sm" variant="secondary" onClick={toggleEnabled} disabled={update.isPending}>
            <Power className="size-4" /> {disabled ? "Включить" : "Выключить"}
          </Button>
          <EditButton name={account.label} onClick={onEdit} />
          <ConfirmDeleteButton
            kind="LLM-аккаунт"
            name={account.label}
            pending={deleteAccount.isPending}
            onConfirm={() =>
              deleteAccount.mutate(account.id, {
                onError: (error) => toast.error(errorMessage(error, "Не удалось удалить")),
              })}
          />
        </div>
      </div>
    </Card>
  );
}
