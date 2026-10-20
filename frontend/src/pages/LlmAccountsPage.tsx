import { useState } from "react";
import { KeyRound, Plus } from "lucide-react";
import { toast } from "sonner";
import { PageHeader } from "@/components/layout/PageHeader";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { LlmAccountForm } from "@/components/llmAccounts/LlmAccountForm";
import { useDeleteLlmAccount, useLlmAccounts } from "@/hooks/useLlmAccounts";
import { ApiError } from "@/lib/apiClient";
import type { LlmAccount } from "@/lib/types";
import { ConfirmDeleteButton } from "@/components/common/actions/ConfirmDeleteButton";
import { EditButton } from "@/components/common/actions/EditButton";
import { LLM_ACCOUNT_STATUS_LABEL, LLM_ACCOUNT_STATUS_TONE } from "@/lib/labels";
import { EmptyState } from "@/components/common/feedback/EmptyState";
import { PAGE_BODY, PAGE_ROOT } from "@/styles/classes";
import { LoadingState } from "@/components/common/feedback/LoadingState";

export function LlmAccountsPage() {
  const { data: accounts, isLoading } = useLlmAccounts();
  const deleteAccount = useDeleteLlmAccount();
  const [dialogAccount, setDialogAccount] = useState<LlmAccount | "new" | null>(null);

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
        {!isLoading && (accounts ?? []).length === 0 && (
          <EmptyState
            icon={KeyRound}
            title="LLM-аккаунтов пока нет"
            hint="Без аккаунта Claude задачи не запустятся. Нажмите «+ Аккаунт» вверху справа и укажите каталог конфигурации Claude, в котором уже выполнен вход."
          />
        )}
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
          {(accounts ?? []).map((account) => (
            <Card key={account.id} className="flex flex-col gap-1.5">
              <div className="flex items-center gap-1">
                <div className="min-w-0 flex-1 truncate font-bold" title={account.label}>
                  {account.label}
                </div>
                <EditButton name={account.label} onClick={() => setDialogAccount(account)} />
                <ConfirmDeleteButton
                  kind="LLM-аккаунт"
                  name={account.label}
                  pending={deleteAccount.isPending}
                  onConfirm={() =>
                    deleteAccount.mutate(account.id, {
                      onError: (error) =>
                        toast.error(
                          error instanceof ApiError ? error.message : "Не удалось удалить",
                        ),
                    })}
                />
              </div>
              <div className="truncate font-mono text-small text-text-3" title={account.claude_config_dir}>
                {account.claude_config_dir}
              </div>
              <Badge tone={LLM_ACCOUNT_STATUS_TONE[account.status]} className="self-start">
                {LLM_ACCOUNT_STATUS_LABEL[account.status]}
              </Badge>
            </Card>
          ))}
        </div>
      </div>

      <Dialog open={dialogAccount !== null} onOpenChange={(open) => !open && setDialogAccount(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {dialogAccount === "new" ? "Новый LLM-аккаунт" : "Редактировать LLM-аккаунт"}
            </DialogTitle>
          </DialogHeader>
          {dialogAccount !== null && (
            <LlmAccountForm
              account={dialogAccount === "new" ? undefined : dialogAccount}
              onSaved={() => setDialogAccount(null)}
              onCancel={() => setDialogAccount(null)}
            />
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
