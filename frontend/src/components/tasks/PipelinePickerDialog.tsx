import { useState } from "react";
import { toast } from "sonner";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Button } from "@/components/ui/button";
import { usePipelines } from "@/hooks/usePipelines";
import { useBindPipeline } from "@/hooks/useTasks";
import { ApiError } from "@/lib/apiClient";
import type { Task } from "@/lib/types";

export function PipelinePickerDialog({
  task,
  open,
  onOpenChange,
}: {
  task: Task;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { data: pipelines } = usePipelines();
  const bindPipeline = useBindPipeline(task.id);
  const [pipelineId, setPipelineId] = useState("");

  function handleBind() {
    if (!pipelineId) return;
    bindPipeline.mutate(pipelineId, {
      onSuccess: () => onOpenChange(false),
      onError: (error) => {
        toast.error(error instanceof ApiError ? error.message : "Не удалось привязать пайплайн");
      },
    });
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Выбрать пайплайн</DialogTitle>
        </DialogHeader>
        <Select value={pipelineId} onValueChange={setPipelineId}>
          <SelectTrigger>
            <SelectValue placeholder="Выберите пайплайн" />
          </SelectTrigger>
          <SelectContent>
            {(pipelines ?? []).map((pipeline) => (
              <SelectItem key={pipeline.id} value={pipeline.id}>
                {pipeline.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <DialogFooter>
          <Button variant="secondary" onClick={() => onOpenChange(false)}>
            Отмена
          </Button>
          <Button onClick={handleBind} disabled={!pipelineId || bindPipeline.isPending}>
            Привязать
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
