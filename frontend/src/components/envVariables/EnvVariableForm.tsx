import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { DialogFooter } from "@/components/ui/dialog";
import { useCreateEnvVariable, useUpdateEnvVariable } from "@/hooks/useEnvVariables";
import { useRepositories } from "@/hooks/useRepositories";
import { ApiError } from "@/lib/apiClient";
import { EnvVariableScope, type EnvVariable } from "@/lib/types";
import { ENV_SCOPE_LABEL } from "@/lib/labels";
import { EmptyState } from "@/components/common/feedback/EmptyState";

/**
 * Создание и редактирование переменной окружения. У существующей меняются
 * только значение и признак секрета: ключ и область видимости API не правит.
 */
export function EnvVariableForm({
  envVariable,
  onSaved,
  onCancel,
}: {
  envVariable?: EnvVariable;
  onSaved: () => void;
  onCancel: () => void;
}) {
  const { data: repositories } = useRepositories();
  const createEnvVariable = useCreateEnvVariable();
  const updateEnvVariable = useUpdateEnvVariable(envVariable?.id ?? "");
  const [key, setKey] = useState(envVariable?.key ?? "");
  const [value, setValue] = useState("");
  const [isSecret, setIsSecret] = useState(envVariable?.is_secret ?? true);
  const [scope, setScope] = useState<EnvVariableScope>(envVariable?.scope ?? EnvVariableScope.GLOBAL);
  const [repositoryId, setRepositoryId] = useState(envVariable?.repository_id ?? "");

  function handleSave() {
    const onError = (error: unknown) =>
      toast.error(error instanceof ApiError ? error.message : "Не удалось сохранить переменную");
    if (envVariable) {
      // Значение хранится зашифрованным: пустое поле — оставить прежнее.
      updateEnvVariable.mutate(
        { is_secret: isSecret, ...(value ? { value } : {}) },
        { onSuccess: onSaved, onError },
      );
    } else {
      createEnvVariable.mutate(
        {
          key,
          value,
          is_secret: isSecret,
          scope,
          repository_id: scope === EnvVariableScope.REPOSITORY ? repositoryId : undefined,
        },
        { onSuccess: onSaved, onError },
      );
    }
  }

  const isPending = createEnvVariable.isPending || updateEnvVariable.isPending;
  const repositoryName = repositories?.find((repository) => repository.id === repositoryId)?.name;

  return (
    <>
      <div className="flex flex-col gap-3">
        {envVariable ? (
          <div className="rounded-md border border-border p-3">
            <div className="truncate font-mono text-body font-bold" title={envVariable.key}>
              {envVariable.key}
            </div>
            <div className="mt-0.5 text-meta text-text-3">
              {ENV_SCOPE_LABEL[envVariable.scope]}
              {repositoryName && ` · ${repositoryName}`} — ключ и область видимости не меняются
            </div>
          </div>
        ) : (
          <div>
            <Label htmlFor="env-key">Ключ</Label>
            <Input
              id="env-key"
              placeholder="GITLAB_API_TOKEN"
              value={key}
              onChange={(e) => setKey(e.target.value)}
            />
          </div>
        )}
        <div>
          <Label htmlFor="env-value">
            {envVariable ? "Новое значение (оставьте пустым, чтобы не менять)" : "Значение"}
          </Label>
          <Input
            id="env-value"
            type="password"
            value={value}
            onChange={(e) => setValue(e.target.value)}
          />
        </div>
        {!envVariable && (
          <div>
            <Label>Область видимости</Label>
            <Select value={scope} onValueChange={(v) => setScope(v as EnvVariableScope)}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={EnvVariableScope.GLOBAL}>
                  {ENV_SCOPE_LABEL[EnvVariableScope.GLOBAL]}
                </SelectItem>
                <SelectItem value={EnvVariableScope.REPOSITORY}>
                  {ENV_SCOPE_LABEL[EnvVariableScope.REPOSITORY]}
                </SelectItem>
              </SelectContent>
            </Select>
          </div>
        )}
        {!envVariable && scope === EnvVariableScope.REPOSITORY && (
          <div>
            <Label>Репозиторий</Label>
            <Select value={repositoryId} onValueChange={setRepositoryId}>
              <SelectTrigger>
                <SelectValue placeholder="Выберите репозиторий" />
              </SelectTrigger>
              <SelectContent>
                {(repositories ?? []).map((repository) => (
                  <SelectItem key={repository.id} value={repository.id}>
                    {repository.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {repositories && repositories.length === 0 && (
              <EmptyState
                compact
                title="Репозиториев пока нет"
                hint="Подключите репозиторий в разделе «Репозитории» кнопкой «+ Репозиторий» или сделайте переменную глобальной."
              />
            )}
          </div>
        )}
        <label className="flex items-center gap-2 text-body font-semibold">
          <Checkbox checked={isSecret} onCheckedChange={(v) => setIsSecret(v === true)} />
          Секретное значение
        </label>
      </div>
      <DialogFooter>
        <Button variant="secondary" onClick={onCancel}>
          Отмена
        </Button>
        <Button
          onClick={handleSave}
          disabled={
            isPending ||
            (!envVariable &&
              (!key || !value || (scope === EnvVariableScope.REPOSITORY && !repositoryId)))
          }
        >
          {envVariable ? "Сохранить" : "Создать"}
        </Button>
      </DialogFooter>
    </>
  );
}
