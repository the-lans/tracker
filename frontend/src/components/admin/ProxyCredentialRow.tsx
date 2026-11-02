import { RefreshCw, TimerReset } from "lucide-react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { ConfirmDeleteButton } from "@/components/common/actions/ConfirmDeleteButton";
import {
  useDeleteProxyCredential,
  useRefreshProxyCredential,
  useResetProxyCooldown,
} from "@/hooks/useAdmin";
import { toastError } from "@/lib/errors";
import { LLM_ACCOUNT_STATUS_LABEL, LLM_ACCOUNT_STATUS_TONE } from "@/lib/labels";
import type { ProxyCredential } from "@/lib/types";

function usageText(credential: ProxyCredential): string | null {
  const parts = [
    credential.usage_5h_pct !== null ? `5 ч ${Number(credential.usage_5h_pct)}%` : null,
    credential.usage_week_pct !== null ? `нед. ${Number(credential.usage_week_pct)}%` : null,
  ].filter(Boolean);
  return parts.length ? parts.join(" · ") : null;
}

/** Раздел 15.5: учётка прокси — владелец, провайдер, статус, расход и действия. */
export function ProxyCredentialRow({ credential }: { credential: ProxyCredential }) {
  const refresh = useRefreshProxyCredential();
  const resetCooldown = useResetProxyCooldown();
  const remove = useDeleteProxyCredential();
  const orphan = credential.account_id === null;
  const usage = usageText(credential);

  return (
    <Card className="flex flex-col gap-2 md:flex-row md:items-center">
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="truncate font-bold" title={credential.account_label ?? credential.name}>
            {credential.account_label ?? "без владельца"}
          </span>
          {credential.account_status && (
            <Badge tone={LLM_ACCOUNT_STATUS_TONE[credential.account_status]}>
              {LLM_ACCOUNT_STATUS_LABEL[credential.account_status]}
            </Badge>
          )}
          {orphan && <Badge tone="warning">без владельца</Badge>}
          {credential.disabled && <Badge tone="neutral">выключена в прокси</Badge>}
          {credential.requires_sign_in && <Badge tone="warning">нужен вход</Badge>}
          {credential.quota_blocked && <Badge tone="danger">пауза после ошибки</Badge>}
        </div>
        <div className="truncate text-meta text-text-3" title={credential.name}>
          {credential.provider} · {credential.owner_email ?? "—"}
          {usage && ` · ${usage}`}
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-1">
        <Button
          size="sm"
          variant="secondary"
          disabled={refresh.isPending}
          onClick={() =>
            refresh.mutate(credential.name, {
              onSuccess: () => toast.success("Токен учётки обновлён"),
              onError: toastError("Не удалось обновить токен"),
            })}
        >
          <RefreshCw className="size-3.5" /> Обновить токен
        </Button>
        {credential.quota_blocked && (
          <Button
            size="sm"
            variant="secondary"
            disabled={resetCooldown.isPending}
            onClick={() =>
              resetCooldown.mutate(credential.name, {
                onSuccess: () => toast.success("Пауза учётки снята"),
                onError: toastError("Не удалось снять паузу"),
              })}
          >
            <TimerReset className="size-3.5" /> Снять паузу
          </Button>
        )}
        {orphan && (
          <ConfirmDeleteButton
            kind="учётку прокси"
            name={credential.name}
            pending={remove.isPending}
            onConfirm={() => remove.mutate(credential.name, { onError: toastError("Не удалось удалить") })}
          />
        )}
      </div>
    </Card>
  );
}
