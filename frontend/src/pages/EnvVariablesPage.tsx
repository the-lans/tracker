import { useState } from "react";
import { Braces, Eye, EyeOff, Plus } from "lucide-react";
import { toast } from "sonner";
import { PageHeader } from "@/components/layout/PageHeader";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { EnvVariableForm } from "@/components/envVariables/EnvVariableForm";
import { useDeleteEnvVariable, useEnvVariables, useRevealEnvVariable } from "@/hooks/useEnvVariables";
import { ApiError } from "@/lib/apiClient";
import { EnvVariableScope, type EnvVariable } from "@/lib/types";
import { ConfirmDeleteButton } from "@/components/common/actions/ConfirmDeleteButton";
import { EditButton } from "@/components/common/actions/EditButton";
import { ENV_SCOPE_LABEL } from "@/lib/labels";
import { EmptyState } from "@/components/common/feedback/EmptyState";
import { PAGE_BODY, PAGE_ROOT } from "@/styles/classes";
import { LoadingState } from "@/components/common/feedback/LoadingState";

function RevealValue({ envVariableId }: { envVariableId: string }) {
  const [value, setValue] = useState<string | null>(null);
  const reveal = useRevealEnvVariable();

  if (value !== null) {
    return (
      <span className="min-w-0 max-w-[45%] truncate font-mono text-small" title={value}>
        {value}
      </span>
    );
  }

  return (
    <button
      type="button"
      className="touch-target inline-flex shrink-0 items-center gap-1 text-small font-bold text-accent"
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
  const deleteEnvVariable = useDeleteEnvVariable();
  const [dialogVariable, setDialogVariable] = useState<EnvVariable | "new" | null>(null);
  // Раскрытое значение после правки устарело бы — сохранение сбрасывает все раскрытые.
  const [savedCount, setSavedCount] = useState(0);

  return (
    <div className={PAGE_ROOT}>
      <PageHeader
        title="Переменные окружения"
        actions={
          <Button onClick={() => setDialogVariable("new")}>
            <Plus className="size-4" /> Переменная
          </Button>
        }
      />
      <div className={PAGE_BODY}>
        {isLoading && <LoadingState />}
        {!isLoading && (envVariables ?? []).length === 0 && (
          <EmptyState
            icon={Braces}
            title="Переменных окружения пока нет"
            hint="Нажмите «+ Переменная» вверху справа. Глобальная переменная доступна во всех задачах, переменная репозитория — в задачах с этим репозиторием. В промтах она подставляется как {{env.ИМЯ}}."
          />
        )}
        <div className="flex flex-col gap-2">
          {(envVariables ?? []).map((envVariable) => (
            <Card key={envVariable.id} className="flex items-center gap-3">
              <div className="min-w-0 flex-1">
                <div className="truncate font-mono text-body font-bold" title={envVariable.key}>
                  {envVariable.key}
                </div>
                <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5">
                  <Badge tone={envVariable.scope === EnvVariableScope.GLOBAL ? "info" : "neutral"}>
                    {ENV_SCOPE_LABEL[envVariable.scope]}
                  </Badge>
                  {envVariable.is_secret && (
                    <span className="inline-flex items-center gap-1 text-caption text-text-3">
                      <EyeOff className="size-3" /> секрет
                    </span>
                  )}
                </div>
              </div>
              <RevealValue key={`${envVariable.id}-${savedCount}`} envVariableId={envVariable.id} />
              <EditButton name={envVariable.key} onClick={() => setDialogVariable(envVariable)} />
              <ConfirmDeleteButton
                kind="переменную окружения"
                name={envVariable.key}
                pending={deleteEnvVariable.isPending}
                onConfirm={() =>
                  deleteEnvVariable.mutate(envVariable.id, {
                    onError: (error) =>
                      toast.error(
                        error instanceof ApiError ? error.message : "Не удалось удалить",
                      ),
                  })}
              />
            </Card>
          ))}
        </div>
      </div>

      <Dialog open={dialogVariable !== null} onOpenChange={(open) => !open && setDialogVariable(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {dialogVariable === "new" ? "Новая переменная окружения" : "Редактировать переменную"}
            </DialogTitle>
          </DialogHeader>
          {dialogVariable !== null && (
            <EnvVariableForm
              envVariable={dialogVariable === "new" ? undefined : dialogVariable}
              onSaved={() => {
                setDialogVariable(null);
                setSavedCount((count) => count + 1);
              }}
              onCancel={() => setDialogVariable(null)}
            />
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
