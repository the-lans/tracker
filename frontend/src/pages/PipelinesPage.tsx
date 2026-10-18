import { useState } from "react";
import { Link } from "react-router-dom";
import { Archive, ArchiveRestore, Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { PageHeader } from "@/components/layout/PageHeader";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
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

function PipelineArchiveToggle({ pipeline }: { pipeline: Pipeline }) {
  const updatePipeline = useUpdatePipeline(pipeline.id);
  return (
    <button
      type="button"
      onClick={() =>
        updatePipeline.mutate(
          { is_archived: !pipeline.is_archived },
          {
            onError: (error) =>
              toast.error(error instanceof ApiError ? error.message : "Не удалось изменить"),
          },
        )
      }
      className="touch-target flex items-center justify-center text-text-3 hover:text-text"
      aria-label={pipeline.is_archived ? "Разархивировать" : "Архивировать"}
    >
      {pipeline.is_archived ? <ArchiveRestore className="size-4" /> : <Archive className="size-4" />}
    </button>
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
    <div className="flex h-full flex-col">
      <PageHeader
        title="Пайплайны"
        actions={
          <>
            <label className="flex items-center gap-1.5 text-[12.5px] text-text-2">
              <input
                type="checkbox"
                checked={includeArchived}
                onChange={(e) => setIncludeArchived(e.target.checked)}
              />
              Показать архивные
            </label>
            <Button onClick={() => setOpen(true)}>
              <Plus className="size-4" /> Пайплайн
            </Button>
          </>
        }
      />
      <div className="min-h-0 flex-1 overflow-auto px-5 pb-8 lg:px-8">
        {isLoading && <div className="text-text-3">Загрузка…</div>}
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
          {(pipelines ?? []).map((pipeline) => (
            <Card key={pipeline.id} className="flex items-center gap-2">
              <Link to={`/pipelines/${pipeline.id}`} className="min-w-0 flex-1">
                <div className="truncate font-bold">{pipeline.name}</div>
                {pipeline.is_archived && (
                  <Badge tone="neutral" className="mt-1">
                    архивирован
                  </Badge>
                )}
              </Link>
              <PipelineArchiveToggle pipeline={pipeline} />
              <button
                type="button"
                onClick={() => handleDelete(pipeline.id)}
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
