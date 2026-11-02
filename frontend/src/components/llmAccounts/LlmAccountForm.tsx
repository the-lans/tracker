import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { DialogFooter } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { ReasoningEffortSelect } from "@/components/llmAccounts/ReasoningEffortSelect";
import {
  useCreateLlmAccount,
  useLlmAccountModels,
  useLlmProviders,
  useUpdateLlmAccount,
} from "@/hooks/useLlmAccounts";
import { errorMessage } from "@/lib/errors";
import type { LlmAccount, LlmAccountUpdateRequest, ReasoningEffort } from "@/lib/types";

/**
 * Раздел 15.1: новый аккаунт — пометка и провайдер (вход — следующим шагом,
 * кнопкой «Войти»); после входа — модель из списка учётки и уровень
 * рассуждений по умолчанию. Провайдер после создания не меняется.
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
  const { data: providers } = useLlmProviders();
  const { data: models } = useLlmAccountModels(account?.id ?? "", Boolean(account?.signed_in));
  const [label, setLabel] = useState(account?.label ?? "");
  const [provider, setProvider] = useState(account?.provider ?? "");
  const [model, setModel] = useState(account?.default_model ?? "");
  const [effort, setEffort] = useState<ReasoningEffort | null>(account?.default_effort ?? null);

  function handleSave() {
    const onError = (error: unknown) =>
      toast.error(errorMessage(error, "Не удалось сохранить аккаунт"));
    if (!account) {
      createAccount.mutate({ label, provider }, { onSuccess: onSaved, onError });
      return;
    }
    const body: LlmAccountUpdateRequest = { label };
    if (model && model !== account.default_model) body.default_model = model;
    if (effort && effort !== account.default_effort) body.default_effort = effort;
    updateAccount.mutate(body, { onSuccess: onSaved, onError });
  }

  const isPending = createAccount.isPending || updateAccount.isPending;

  return (
    <>
      <div className="flex flex-col gap-3">
        <div>
          <Label htmlFor="llm-label">Пометка</Label>
          <Input id="llm-label" value={label} onChange={(e) => setLabel(e.target.value)} />
        </div>
        {!account && (
          <div>
            <Label htmlFor="llm-provider">Провайдер</Label>
            <Select value={provider} onValueChange={setProvider}>
              <SelectTrigger id="llm-provider">
                <SelectValue placeholder="Выберите провайдера" />
              </SelectTrigger>
              <SelectContent>
                {(providers ?? []).map((item) => (
                  <SelectItem key={item.id} value={item.id}>
                    {item.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <p className="mt-1 text-meta text-text-3">
              После создания нажмите «Войти»: вход выполняется у провайдера в браузере.
            </p>
          </div>
        )}
        {account && (
          <div>
            <Label htmlFor="llm-model">Модель по умолчанию</Label>
            {account.signed_in ? (
              <Select value={model} onValueChange={setModel}>
                <SelectTrigger id="llm-model">
                  <SelectValue placeholder="Выберите модель" />
                </SelectTrigger>
                <SelectContent>
                  {(models ?? []).map((item) => (
                    <SelectItem key={item} value={item}>
                      {item}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            ) : (
              <p className="text-meta text-text-3">Список моделей появится после входа в аккаунт.</p>
            )}
          </div>
        )}
        {account && (
          <div>
            <Label htmlFor="llm-effort">Уровень рассуждений по умолчанию</Label>
            <ReasoningEffortSelect id="llm-effort" value={effort} onChange={setEffort} />
            <p className="mt-1 text-meta text-text-3">
              Для обращений без уровня ноды: свободный промт, нода без уровня, пересказ родителя.
            </p>
          </div>
        )}
      </div>
      <DialogFooter>
        <Button variant="secondary" onClick={onCancel}>
          Отмена
        </Button>
        <Button onClick={handleSave} disabled={!label || (!account && !provider) || isPending}>
          {account ? "Сохранить" : "Создать"}
        </Button>
      </DialogFooter>
    </>
  );
}
