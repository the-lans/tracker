import { useState } from "react";
import { ExternalLink, Plus } from "lucide-react";
import { toast } from "sonner";
import { Card } from "@/components/ui/card";
import { Switch } from "@/components/ui/switch";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useUpdateTask } from "@/hooks/useTasks";
import { ApiError } from "@/lib/apiClient";
import { TaskRepositoriesCard } from "@/components/tasks/TaskRepositoriesCard";
import { TaskEnvVariablesCard } from "@/components/tasks/TaskEnvVariablesCard";
import { TaskArtifactsCard } from "@/components/tasks/TaskArtifactsCard";
import { ParentTaskCard } from "@/components/tasks/ParentTaskCard";
import { useNodes } from "@/hooks/useNodes";
import { formatDateTime } from "@/lib/utils";
import {
  TaskStatus,
  type NodeLog,
  type Task,
  type TaskUpdateRequest,
} from "@/lib/types";
import { TaskLibraryPromptsCard } from "@/components/tasks/TaskLibraryPromptsCard";
import { PipelinePickerDialog } from "@/components/tasks/PipelinePickerDialog";
import { TaskNodesCard } from "@/components/tasks/TaskNodesCard";

/** ISO-время ↔ значение `<input type="datetime-local">` в локальной зоне. */
function toLocalInputValue(iso: string | null): string {
  if (!iso) return "";
  const date = new Date(iso);
  const offsetMs = date.getTimezoneOffset() * 60_000;
  return new Date(date.getTime() - offsetMs).toISOString().slice(0, 16);
}

export function TaskOverviewPanel({
  task,
  nodeLogs,
}: {
  task: Task;
  nodeLogs: NodeLog[];
}) {
  const updateTask = useUpdateTask(task.id);
  const isNew = task.status === TaskStatus.NEW;

  function update(body: TaskUpdateRequest) {
    updateTask.mutate(body, {
      onError: (error) => {
        toast.error(
          error instanceof ApiError
            ? error.message
            : "Не удалось сохранить изменения",
        );
      },
    });
  }
  const { data: libraryNodes } = useNodes({ libraryOnly: true });
  const [pipelinePickerOpen, setPipelinePickerOpen] = useState(false);

  return (
    <div className="flex flex-col gap-4 overflow-auto p-5 short:overflow-visible">
      <div className="px-0.5 text-caption font-extrabold uppercase tracking-wider text-text-3">
        Обзор
      </div>

      <Card>
        <div className="mb-1 text-meta font-bold text-text-3">Описание</div>
        <div className="text-body leading-relaxed text-text-2">
          {task.description}
        </div>
        {task.guide_url && (
          <>
            <div className="mb-1 mt-2.5 text-meta font-bold text-text-3">
              Гайд
            </div>
            <a
              href={task.guide_url}
              target="_blank"
              rel="noreferrer"
              className="touch-target inline-flex items-center gap-1.5 rounded-lg bg-info-tint px-2.5 py-1.5 text-note font-bold text-info-text"
            >
              <ExternalLink className="size-3.5" />
              Открыть гайд
            </a>
          </>
        )}
      </Card>

      {task.parent_task_id && <ParentTaskCard task={task} />}

      {isNew ? (
        <>
          {/* До запуска — порядок настройки: окружение, расписание, пайплайн. */}
          <TaskRepositoriesCard taskId={task.id} />
          <TaskEnvVariablesCard task={task} />
          <TaskArtifactsCard task={task} />
        <Card>
          <div className="flex items-center justify-between py-1">
            <div>
              <div className="text-body font-bold">Автозапуск</div>
              <div className="mt-0.5 text-meta text-text-3">
                {task.scheduled_start_at
                  ? formatDateTime(task.scheduled_start_at)
                  : "Дата и время старта"}
              </div>
            </div>
            <Switch
              checked={task.auto_start_enabled}
              disabled={updateTask.isPending}
              onCheckedChange={(checked) =>
                update({ auto_start_enabled: checked })
              }
            />
          </div>
          {/* Раздел 12.1: пока переключатель выключен, поле даты неактивно. */}
          <Input
            type="datetime-local"
            aria-label="Дата и время автозапуска"
            className="mt-2"
            value={toLocalInputValue(task.scheduled_start_at)}
            disabled={!task.auto_start_enabled || updateTask.isPending}
            onChange={(event) =>
              update({
                scheduled_start_at: event.target.value
                  ? new Date(event.target.value).toISOString()
                  : null,
              })
            }
          />
        </Card>
        <Card>
          <div className="flex items-center justify-between py-1">
            <div>
              <div className="text-body font-bold">
                Принять план автоматически
              </div>
              <div className="mt-0.5 text-meta text-text-3">
                Без остановки на ревью плана
              </div>
            </div>
            <Switch
              checked={task.auto_accept_plan}
              disabled={task.status === TaskStatus.DONE || updateTask.isPending}
              onCheckedChange={(checked) => update({ auto_accept_plan: checked })}
            />
          </div>
        </Card>
        {task.pipeline_id ? (
          <TaskNodesCard task={task} nodeLogs={nodeLogs} />
        ) : (
          <Card>
            <div className="mb-2 text-body text-text-2">Пайплайн не выбран</div>
            {task.status === TaskStatus.NEW && (
              <Button
                size="sm"
                variant="secondary"
                onClick={() => setPipelinePickerOpen(true)}
              >
                <Plus className="size-4" />
                Выбрать пайплайн
              </Button>
            )}
          </Card>
        )}
        <TaskLibraryPromptsCard task={task} libraryNodes={libraryNodes ?? []} />
        </>
      ) : (
        <>
          {/* После запуска — сначала то, чем управляют во время работы. */}
        <Card>
          <div className="flex items-center justify-between py-1">
            <div>
              <div className="text-body font-bold">
                Принять план автоматически
              </div>
              <div className="mt-0.5 text-meta text-text-3">
                Без остановки на ревью плана
              </div>
            </div>
            <Switch
              checked={task.auto_accept_plan}
              disabled={task.status === TaskStatus.DONE || updateTask.isPending}
              onCheckedChange={(checked) => update({ auto_accept_plan: checked })}
            />
          </div>
        </Card>
        {task.pipeline_id ? (
          <TaskNodesCard task={task} nodeLogs={nodeLogs} />
        ) : (
          <Card>
            <div className="mb-2 text-body text-text-2">Пайплайн не выбран</div>
            {task.status === TaskStatus.NEW && (
              <Button
                size="sm"
                variant="secondary"
                onClick={() => setPipelinePickerOpen(true)}
              >
                <Plus className="size-4" />
                Выбрать пайплайн
              </Button>
            )}
          </Card>
        )}
        <TaskLibraryPromptsCard task={task} libraryNodes={libraryNodes ?? []} />
          <TaskRepositoriesCard taskId={task.id} />
          <TaskEnvVariablesCard task={task} />
          <TaskArtifactsCard task={task} />
          {/* Автозапуск после старта уже не настраивается — одна строка вместо формы. */}
          <Card className="flex items-center justify-between gap-3 py-3">
            <div className="text-body font-bold">Автозапуск</div>
            <div className="text-small text-text-3">
              {task.auto_start_enabled && task.scheduled_start_at
                ? `был запланирован на ${formatDateTime(task.scheduled_start_at)}`
                : "не использовался"}
            </div>
          </Card>
        </>
      )}

      <PipelinePickerDialog
        task={task}
        open={pipelinePickerOpen}
        onOpenChange={setPipelinePickerOpen}
      />
    </div>
  );
}
