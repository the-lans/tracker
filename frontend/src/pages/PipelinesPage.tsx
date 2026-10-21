import { useState } from "react";
import { Link } from "react-router-dom";
import { Plus, Workflow } from "lucide-react";
import { toast } from "sonner";
import { PageHeader } from "@/components/layout/PageHeader";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  useCreatePipeline,
  useDeletePipeline,
  usePipelines,
  useUpdatePipeline,
} from "@/hooks/usePipelines";
import { ApiError } from "@/lib/apiClient";
import type { Pipeline } from "@/lib/types";
import { ArchiveToggleButton } from "@/components/common/actions/ArchiveToggleButton";
import { ConfirmDeleteButton } from "@/components/common/actions/ConfirmDeleteButton";
import { OwnerLabel } from "@/components/common/avatar/OwnerLabel";
import { EmptyState } from "@/components/common/feedback/EmptyState";
import { PAGE_BODY, PAGE_ROOT } from "@/styles/classes";
import { LoadingState } from "@/components/common/feedback/LoadingState";

function PipelineArchiveToggle({ pipeline }: { pipeline: Pipeline }) {
  const updatePipeline = useUpdatePipeline(pipeline.id);
  return (
    <ArchiveToggleButton
      name={pipeline.name}
      archived={pipeline.is_archived}
      pending={updatePipeline.isPending}
      onToggle={() =>
        updatePipeline.mutate(
          { is_archived: !pipeline.is_archived },
          {
            onError: (error) =>
              toast.error(error instanceof ApiError ? error.message : "Не удалось изменить"),
          },
        )
      }
    />
  );
}

export function PipelinesPage() {
  const [includeArchived, setIncludeArchived] = useState(false);
  const { data: pipelines, isLoading } = usePipelines(includeArchived);
  const createPipeline = useCreatePipeline();
  const deletePipeline = useDeletePipeline();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");

  function handleCreate() {
    createPipeline.mutate(name, {
      onSuccess: () => {
        setOpen(false);
        setName("");
      },
      onError: (error) => {
        toast.error(error instanceof ApiError ? error.message : "Не удалось создать пайплайн");
      },
    });
  }

  function handleDelete(id: string) {
    deletePipeline.mutate(id, {
      onError: (error) => {
        const message =
          error instanceof ApiError && error.status === 409
            ? "Пайплайн используется задачей — доступна только архивация"
            : "Не удалось удалить пайплайн";
        toast.error(message);
      },
    });
  }

  return (
    <div className={PAGE_ROOT}>
      <PageHeader
        title="Пайплайны"
        actions={
          <>
            <label className="flex min-h-11 items-center gap-2.5 text-note text-text-2">
              <Checkbox
                checked={includeArchived}
                onCheckedChange={(checked) => setIncludeArchived(checked === true)}
              />
              Показать архивные
            </label>
            <Button onClick={() => setOpen(true)}>
              <Plus className="size-4" /> Пайплайн
            </Button>
          </>
        }
      />
      <div className={PAGE_BODY}>
        {isLoading && <LoadingState />}
        {!isLoading && (pipelines ?? []).length === 0 && (
          <EmptyState
            icon={Workflow}
            title={includeArchived ? "Пайплайнов пока нет" : "Активных пайплайнов нет"}
            hint="Пайплайн — цепочка шагов (нод), которую агент выполняет в задаче. Нажмите «+ Пайплайн» вверху справа, задайте название, затем добавьте ноды: промт, слэш-команду, скрипт, режим планирования или очистку контекста."
          />
        )}
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
          {(pipelines ?? []).map((pipeline) => (
            <Card key={pipeline.id} className="flex items-center gap-2">
              <Link to={`/pipelines/${pipeline.id}`} className="flex min-h-11 min-w-0 flex-1 flex-col justify-center">
                <div className="truncate font-bold" title={pipeline.name}>{pipeline.name}</div>
                {pipeline.is_archived && (
                  <Badge tone="neutral" className="mt-1">
                    архивирован
                  </Badge>
                )}
                <OwnerLabel ownerId={pipeline.created_by} />
              </Link>
              <PipelineArchiveToggle pipeline={pipeline} />
              <ConfirmDeleteButton
                kind="пайплайн"
                name={pipeline.name}
                pending={deletePipeline.isPending}
                onConfirm={() => handleDelete(pipeline.id)}
              />
            </Card>
          ))}
        </div>
      </div>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Новый пайплайн</DialogTitle>
          </DialogHeader>
          <div>
            <Label htmlFor="pipeline-name">Название</Label>
            <Input id="pipeline-name" value={name} onChange={(e) => setName(e.target.value)} />
          </div>
          <DialogFooter>
            <Button variant="secondary" onClick={() => setOpen(false)}>
              Отмена
            </Button>
            <Button onClick={handleCreate} disabled={!name || createPipeline.isPending}>
              Создать
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
