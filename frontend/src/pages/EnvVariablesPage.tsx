import { useState } from "react";
import { Eye, EyeOff, Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { PageHeader } from "@/components/layout/PageHeader";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  useCreateEnvVariable,
  useDeleteEnvVariable,
  useEnvVariables,
  useRevealEnvVariable,
} from "@/hooks/useEnvVariables";
import { useRepositories } from "@/hooks/useRepositories";
import { ApiError } from "@/lib/apiClient";
import { EnvVariableScope } from "@/lib/types";

function RevealValue({ envVariableId }: { envVariableId: string }) {
  const [value, setValue] = useState<string | null>(null);
  const reveal = useRevealEnvVariable();

  if (value !== null) {
    return <span className="font-mono text-[12px]">{value}</span>;
  }

  return (
    <button
      type="button"
      className="inline-flex items-center gap-1 text-[12px] font-bold text-accent"
      onClick={() =>
        reveal.mutate(envVariableId, {
          onSuccess: (data) => setValue(data.value),
          onError: (error) =>
            toast.error(error instanceof ApiError ? error.message : "Не удалось показать значение"),
        })
      }
    >
      <Eye className="size-3.5" /> Показать
    </button>
  );
}

export function EnvVariablesPage() {
  const { data: envVariables, isLoading } = useEnvVariables();
  const { data: repositories } = useRepositories();
  const createEnvVariable = useCreateEnvVariable();
  const deleteEnvVariable = useDeleteEnvVariable();
  const [open, setOpen] = useState(false);
  const [key, setKey] = useState("");
  const [value, setValue] = useState("");
  const [isSecret, setIsSecret] = useState(true);
  const [scope, setScope] = useState<EnvVariableScope>(EnvVariableScope.GLOBAL);
  const [repositoryId, setRepositoryId] = useState<string>("");

  function handleCreate() {
    createEnvVariable.mutate(
      {
        key,
        value,
        is_secret: isSecret,
        scope,
        repository_id: scope === EnvVariableScope.REPOSITORY ? repositoryId : undefined,
      },
      {
        onSuccess: () => {
          setOpen(false);
          setKey("");
          setValue("");
        },
        onError: (error) => {
          toast.error(error instanceof ApiError ? error.message : "Не удалось создать переменную");
        },
      },
    );
  }

  return (
    <div className="flex h-full flex-col">
      <PageHeader
        title="Переменные окружения"
        actions={
          <Button onClick={() => setOpen(true)}>
            <Plus className="size-4" /> Переменная
          </Button>
        }
      />
      <div className="min-h-0 flex-1 overflow-auto px-5 pb-8 lg:px-8">
        {isLoading && <div className="text-text-3">Загрузка…</div>}
        <div className="flex flex-col gap-2">
          {(envVariables ?? []).map((envVariable) => (
            <Card key={envVariable.id} className="flex items-center gap-3">
              <div className="min-w-0 flex-1">
                <div className="font-mono text-[13px] font-bold">{envVariable.key}</div>
                <div className="mt-0.5 flex items-center gap-2">
                  <Badge tone={envVariable.scope === EnvVariableScope.GLOBAL ? "info" : "neutral"}>
                    {envVariable.scope}
                  </Badge>
                  {envVariable.is_secret && (
                    <span className="inline-flex items-center gap-1 text-[11px] text-text-3">
                      <EyeOff className="size-3" /> секрет
                    </span>
                  )}
                </div>
              </div>
              <RevealValue envVariableId={envVariable.id} />
              <button
                type="button"
                onClick={() =>
                  deleteEnvVariable.mutate(envVariable.id, {
                    onError: (error) =>
                      toast.error(
                        error instanceof ApiError ? error.message : "Не удалось удалить",
                      ),
                  })
                }
                className="touch-target flex items-center justify-center text-text-3 hover:text-danger"
                aria-label="Удалить"
              >
                <Trash2 className="size-4" />
              </button>
            </Card>
          ))}
        </div>
      </div>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Новая переменная окружения</DialogTitle>
          </DialogHeader>
          <div className="flex flex-col gap-3">
            <div>
              <Label htmlFor="env-key">Ключ</Label>
              <Input
                id="env-key"
                placeholder="GITLAB_API_TOKEN"
                value={key}
                onChange={(e) => setKey(e.target.value)}
              />
            </div>
            <div>
              <Label htmlFor="env-value">Значение</Label>
              <Input
                id="env-value"
                type="password"
                value={value}
                onChange={(e) => setValue(e.target.value)}
              />
            </div>
            <div>
              <Label>Область видимости</Label>
              <Select value={scope} onValueChange={(v) => setScope(v as EnvVariableScope)}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={EnvVariableScope.GLOBAL}>global</SelectItem>
                  <SelectItem value={EnvVariableScope.REPOSITORY}>repository</SelectItem>
                </SelectContent>
              </Select>
            </div>
            {scope === EnvVariableScope.REPOSITORY && (
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
              </div>
            )}
            <label className="flex items-center gap-2 text-[13px] font-semibold">
              <Checkbox checked={isSecret} onCheckedChange={(v) => setIsSecret(v === true)} />
              Секретное значение
            </label>
          </div>
          <DialogFooter>
            <Button variant="secondary" onClick={() => setOpen(false)}>
              Отмена
            </Button>
            <Button
              onClick={handleCreate}
              disabled={
                !key ||
                !value ||
                (scope === EnvVariableScope.REPOSITORY && !repositoryId) ||
                createEnvVariable.isPending
              }
            >
              Создать
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
