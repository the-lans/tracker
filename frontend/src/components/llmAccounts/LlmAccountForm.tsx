import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { DialogFooter } from "@/components/ui/dialog";
import { useCreateLlmAccount, useUpdateLlmAccount } from "@/hooks/useLlmAccounts";
import { errorMessage } from "@/lib/errors";
import { LlmAccountStatus, type LlmAccount, type LlmAccountUpdateRequest } from "@/lib/types";

/**
 * Создание и редактирование LLM-аккаунта. Вручную аккаунт только включают
 * и отключают: «упёрся в лимит» ставит и снимает система (раздел 16.2).
 */
export function LlmAccountForm({
  account,
  onSaved,
  onCancel,
}: {
  account?: LlmAccount;
  onSaved: () => void;
  onCancel: () => void;
}) {
  const createAccount = useCreateLlmAccount();
  const updateAccount = useUpdateLlmAccount(account?.id ?? "");
  const [label, setLabel] = useState(account?.label ?? "");
  const [configDir, setConfigDir] = useState(account?.claude_config_dir ?? "");
  const wasEnabled = account?.status !== LlmAccountStatus.DISABLED;
  const [enabled, setEnabled] = useState(wasEnabled);

  function handleSave() {
    const onError = (error: unknown) =>
      toast.error(errorMessage(error, "Не удалось сохранить аккаунт"));
    if (account) {
      const body: LlmAccountUpdateRequest = { label, claude_config_dir: configDir };
      // Статус отправляется только при переключении — иначе «упёрся в лимит» сбросился бы в «активен».
      if (enabled !== wasEnabled) {
        body.status = enabled ? LlmAccountStatus.ACTIVE : LlmAccountStatus.DISABLED;
      }
      updateAccount.mutate(body, { onSuccess: onSaved, onError });
    } else {
      createAccount.mutate({ label, claude_config_dir: configDir }, { onSuccess: onSaved, onError });
    }
  }

  const isPending = createAccount.isPending || updateAccount.isPending;

  return (
    <>
      <div className="flex flex-col gap-3">
        <div>
          <Label htmlFor="llm-label">Название</Label>
          <Input id="llm-label" value={label} onChange={(e) => setLabel(e.target.value)} />
        </div>
        <div>
          <Label htmlFor="llm-dir">Каталог конфигурации Claude</Label>
          <Input
            id="llm-dir"
            placeholder="/data/claude-accounts/my-account"
            value={configDir}
            onChange={(e) => setConfigDir(e.target.value)}
          />
          <p className="mt-1 text-meta text-text-3">
            Каталог внутри <code className="font-mono">/data/claude-accounts</code>, не
            пересекается с каталогами других аккаунтов. Сохраните аккаунт и попросите
            администратора выполнить в этом каталоге вход в Claude
            {" "}(<code className="font-mono">claude auth login</code>).
          </p>
        </div>
        {account && (
          <div className="flex items-center justify-between gap-3 rounded-md border border-border p-3">
            <div>
              <div className="text-body font-bold">Аккаунт включён</div>
              <div className="text-meta text-text-3">
                Отключённый вручную аккаунт система сама не включает — только вы
              </div>
            </div>
            <Switch aria-label="Аккаунт включён" checked={enabled} onCheckedChange={setEnabled} />
          </div>
        )}
      </div>
      <DialogFooter>
        <Button variant="secondary" onClick={onCancel}>
          Отмена
        </Button>
        <Button onClick={handleSave} disabled={!label || !configDir || isPending}>
          {account ? "Сохранить" : "Создать"}
        </Button>
      </DialogFooter>
    </>
  );
}
