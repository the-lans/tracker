import { useState } from "react";
import { KeyRound, Plus } from "lucide-react";
import { toast } from "sonner";
import { PageHeader } from "@/components/layout/PageHeader";
import { Button } from "@/components/ui/button";
import { LlmAccountForm } from "@/components/llmAccounts/LlmAccountForm";
import { LlmAccountLoginDialog } from "@/components/llmAccounts/LlmAccountLoginDialog";
import { LlmAccountRow } from "@/components/llmAccounts/LlmAccountRow";
import { useLlmAccounts, useLlmProviders, useReorderLlmAccounts } from "@/hooks/useLlmAccounts";
import { useProfile } from "@/hooks/useProfile";
import { errorMessage } from "@/lib/errors";
import type { LlmAccount } from "@/lib/types";
import { EmptyState } from "@/components/common/feedback/EmptyState";
import { PAGE_BODY, PAGE_ROOT } from "@/styles/classes";
import { LoadingState } from "@/components/common/feedback/LoadingState";
import { EntityFormDialog, type EditTarget } from "@/components/common/dialogs/EntityFormDialog";

/** Новый порядок: аккаунт `index` меняется местами с соседом на `offset`. */
function swapped(accounts: LlmAccount[], index: number, offset: number): string[] {
  const ids = accounts.map((account) => account.id);
  [ids[index], ids[index + offset]] = [ids[index + offset], ids[index]];
  return ids;
}

/** Раздел 15.1, 19.7: аккаунты пользователя в порядке переключения. */
export function LlmAccountsPage() {
  const { data: accounts, isLoading } = useLlmAccounts();
  const { data: providers } = useLlmProviders();
  const { data: profile } = useProfile();
  const reorder = useReorderLlmAccounts();
  const [dialogAccount, setDialogAccount] = useState<EditTarget<LlmAccount>>(null);
  const [loginAccount, setLoginAccount] = useState<LlmAccount | null>(null);
  const list = accounts ?? [];

  function move(index: number, offset: number) {
    reorder.mutate(swapped(list, index, offset), {
      onError: (error) => toast.error(errorMessage(error, "Не удалось изменить порядок")),
    });
  }

  return (
    <div className={PAGE_ROOT}>
      <PageHeader
        title="LLM-аккаунты"
        actions={
          <Button onClick={() => setDialogAccount("new")}>
            <Plus className="size-4" /> Аккаунт
          </Button>
        }
      />
      <div className={PAGE_BODY}>
        {isLoading && <LoadingState />}
        {!isLoading && list.length === 0 && (
          <EmptyState
            icon={KeyRound}
            title="LLM-аккаунтов пока нет"
            hint="Без аккаунта задачи с LLM-нодами не запустятся. Нажмите «+ Аккаунт», выберите провайдера и войдите в аккаунт."
          />
        )}
        {list.length > 1 && (
          <p className="mb-3 text-meta text-text-3">
            Трекер распределяет задачи по аккаунтам так, чтобы 5-часовые окна лимита стартовали
            по очереди, а расход не переступал порог из профиля; если все аккаунты на пороге,
            задача ждёт сброса.
          </p>
        )}
        <div className="flex flex-col gap-3">
          {list.map((account, index) => (
            <LlmAccountRow
              key={account.id}
              account={account}
              provider={providers?.find((item) => item.id === account.provider)}
              thresholds={profile}
              onMoveUp={index > 0 && !reorder.isPending ? () => move(index, -1) : undefined}
              onMoveDown={
                index < list.length - 1 && !reorder.isPending ? () => move(index, 1) : undefined
              }
              onEdit={() => setDialogAccount(account)}
              onLogin={() => setLoginAccount(account)}
            />
          ))}
        </div>
      </div>

      <EntityFormDialog
        target={dialogAccount}
        onClose={() => setDialogAccount(null)}
        createTitle="Новый LLM-аккаунт"
        editTitle="Редактировать LLM-аккаунт"
      >
        {(item, close) => <LlmAccountForm account={item} onSaved={close} onCancel={close} />}
      </EntityFormDialog>
      {loginAccount && (
        <LlmAccountLoginDialog account={loginAccount} onClose={() => setLoginAccount(null)} />
      )}
    </div>
  );
}
