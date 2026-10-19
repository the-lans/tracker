import { useState } from "react";
import { ExternalLink, Lock, Plus } from "lucide-react";
import { toast } from "sonner";
import { Card, CardTitle } from "@/components/ui/card";
import { Switch } from "@/components/ui/switch";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useUpdateTask } from "@/hooks/useTasks";
import { ApiError } from "@/lib/apiClient";
import type { TaskUpdateRequest } from "@/lib/types";
import { TaskRepositoriesCard } from "@/components/tasks/TaskRepositoriesCard";
import { usePipelineNodes } from "@/hooks/usePipelines";
import { useNodes } from "@/hooks/useNodes";
import { formatDateTime } from "@/lib/utils";
import { TaskStatus, type NodeLog, type Task } from "@/lib/types";
import { NodeTypeIcon } from "@/components/tasks/NodeTypeIcon";
import { TaskLibraryPromptsCard } from "@/components/tasks/TaskLibraryPromptsCard";
import { PipelinePickerDialog } from "@/components/tasks/PipelinePickerDialog";

/** ISO-время ↔ значение `<input type="datetime-local">` в локальной зоне. */
function toLocalInputValue(iso: string | null): string {
  if (!iso) return "";
  const date = new Date(iso);
  const offsetMs = date.getTimezoneOffset() * 60_000;
  return new Date(date.getTime() - offsetMs).toISOString().slice(0, 16);
}

export function TaskOverviewPanel({ task, nodeLogs }: { task: Task; nodeLogs: NodeLog[] }) {
  const updateTask = useUpdateTask(task.id);
  const isNew = task.status === TaskStatus.NEW;

  function update(body: TaskUpdateRequest) {
    updateTask.mutate(body, {
      onError: (error) => {
        toast.error(error instanceof ApiError ? error.message : "Не удалось сохранить изменения");
      },
    });
  }
  const { data: pipelineNodes } = usePipelineNodes(task.pipeline_id ?? undefined);
  const { data: libraryNodes } = useNodes({ libraryOnly: true });
  const [pipelinePickerOpen, setPipelinePickerOpen] = useState(false);

  const successfulPipelineNodeIds = new Set(
    nodeLogs.filter((log) => log.status === "success" && log.node_id).map((log) => log.node_id),
  );
  const currentNodeId = [...nodeLogs]
    .reverse()
    .find((log) => log.status === "running" || log.status === "awaiting_decision")?.node_id;

  return (
    <div className="flex flex-col gap-4 overflow-auto p-5">
      <div className="px-0.5 text-[11px] font-extrabold uppercase tracking-wider text-text-3">
        Обзор
      </div>

      <Card>
        <div className="mb-1 text-[11.5px] font-bold text-text-3">Описание</div>
        <div className="text-[13px] leading-relaxed text-text-2">{task.description}</div>
        {task.guide_url && (
          <>
            <div className="mb-1 mt-2.5 text-[11.5px] font-bold text-text-3">Гайд</div>
            <a
              href={task.guide_url}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1.5 rounded-lg bg-info-tint px-2.5 py-1.5 text-[12.5px] font-bold text-info-text"
            >
              <ExternalLink className="size-3.5" />
              Открыть гайд
            </a>
          </>
        )}
      </Card>

      <TaskRepositoriesCard taskId={task.id} />

      <Card>
        <div className="flex items-center justify-between py-1">
          <div>
            <div className="text-[13px] font-bold">Автозапуск</div>
            <div className="mt-0.5 text-[11.5px] text-text-3">
              {task.scheduled_start_at ? formatDateTime(task.scheduled_start_at) : "Дата и время старта"}
            </div>
          </div>
          <Switch
            checked={task.auto_start_enabled}
            disabled={!isNew || updateTask.isPending}
            onCheckedChange={(checked) => update({ auto_start_enabled: checked })}
          />
        </div>
        {/* Раздел 12.1: пока переключатель выключен, поле даты неактивно. */}
        <Input
          type="datetime-local"
          aria-label="Дата и время автозапуска"
          className="mt-2"
          value={toLocalInputValue(task.scheduled_start_at)}
          disabled={!isNew || !task.auto_start_enabled || updateTask.isPending}
          onChange={(event) =>
            update({
              scheduled_start_at: event.target.value ? new Date(event.target.value).toISOString() : null,
            })
          }
        />
        {!isNew && (
          <div className="mt-2 text-[11px] text-text-3">Автозапуск настраивается только до запуска задачи</div>
        )}
      </Card>

      <Card>
        <div className="flex items-center justify-between py-1">
          <div>
            <div className="text-[13px] font-bold">Принять план автоматически</div>
            <div className="mt-0.5 text-[11.5px] text-text-3">auto_accept_plan</div>
          </div>
          <Switch
            checked={task.auto_accept_plan}
            disabled={task.status === TaskStatus.DONE || updateTask.isPending}
            onCheckedChange={(checked) => update({ auto_accept_plan: checked })}
          />
        </div>
      </Card>

      {task.pipeline_id ? (
        <Card>
          <CardTitle>
            <span>Ноды пайплайна</span>
            {pipelineNodes && (
              <span>
                {successfulPipelineNodeIds.size} / {pipelineNodes.length}
              </span>
            )}
          </CardTitle>
          <div className="flex flex-col">
            {(pipelineNodes ?? []).map((node) => {
              const done = successfulPipelineNodeIds.has(node.id);
              const isCurrent = node.id === currentNodeId;
              return (
                <div
                  key={node.id}
                  className={
                    "flex items-center gap-2.5 border-t border-border py-2 first:border-t-0" +
                    (isCurrent ? " -mx-2 rounded-lg border-t-0 bg-accent-tint px-2" : " opacity-60") +
                    (done ? " opacity-100" : "")
                  }
                >
                  <div
                    className={
                      "size-4 shrink-0 rounded-[5px] border-[1.5px] " +
                      (done ? "border-success bg-success" : "border-text-3")
                    }
                  />
                  <NodeTypeIcon type={node.node_type} className="size-[15px] shrink-0 text-text-2" />
                  <div className="flex-1 truncate text-[12.5px] font-bold">{node.name}</div>
                  <div className="text-[10px] font-bold uppercase tracking-wide text-text-3">
                    {node.node_type}
                  </div>
                </div>
              );
            })}
          </div>
          <div className="mt-2 flex items-center gap-1.5 text-[11px] text-text-3">
            <Lock className="size-3" />
            {task.status === TaskStatus.NEW
              ? "Состав нод редактируется до запуска (требуется API редактирования task_nodes)"
              : "Состав нод заблокирован — задача уже выполняется"}
          </div>
        </Card>
      ) : (
        <Card>
          <div className="mb-2 text-[13px] text-text-2">Пайплайн не выбран</div>
          {task.status === TaskStatus.NEW && (
            <Button size="sm" variant="secondary" onClick={() => setPipelinePickerOpen(true)}>
              <Plus className="size-4" />
              Выбрать пайплайн
            </Button>
          )}
        </Card>
      )}

      <TaskLibraryPromptsCard task={task} libraryNodes={libraryNodes ?? []} />

      <PipelinePickerDialog
        task={task}
        open={pipelinePickerOpen}
        onOpenChange={setPipelinePickerOpen}
      />
    </div>
  );
}
