import { useState } from "react";
import { useUpdateTask } from "@/hooks/useTasks";
import { useNodes } from "@/hooks/useNodes";
import { toastError } from "@/lib/errors";
import { TaskStatus, type NodeLog, type Task, type TaskUpdateRequest } from "@/lib/types";
import { AutoAcceptPlanCard } from "@/components/tasks/AutoAcceptPlanCard";
import { AutoStartCard } from "@/components/tasks/AutoStartCard";
import { AutoStartSummaryCard } from "@/components/tasks/AutoStartSummaryCard";
import { ParentTaskCard } from "@/components/tasks/ParentTaskCard";
import { PipelinePickerDialog } from "@/components/tasks/PipelinePickerDialog";
import { TaskArtifactsCard } from "@/components/tasks/TaskArtifactsCard";
import { TaskDescriptionCard } from "@/components/tasks/TaskDescriptionCard";
import { TaskEnvVariablesCard } from "@/components/tasks/TaskEnvVariablesCard";
import { TaskLibraryPromptsCard } from "@/components/tasks/TaskLibraryPromptsCard";
import { TaskPipelineCard } from "@/components/tasks/TaskPipelineCard";
import { TaskRepositoriesCard } from "@/components/tasks/TaskRepositoriesCard";

export function TaskOverviewPanel({ task, nodeLogs }: { task: Task; nodeLogs: NodeLog[] }) {
  const updateTask = useUpdateTask(task.id);
  const { data: libraryNodes } = useNodes({ libraryOnly: true });
  const [pipelinePickerOpen, setPipelinePickerOpen] = useState(false);

  function update(body: TaskUpdateRequest) {
    updateTask.mutate(body, { onError: toastError("Не удалось сохранить изменения") });
  }

  const environment = (
    <>
      <TaskRepositoriesCard taskId={task.id} />
      <TaskEnvVariablesCard task={task} />
      <TaskArtifactsCard task={task} />
    </>
  );
  const execution = (
    <>
      <AutoAcceptPlanCard task={task} pending={updateTask.isPending} onUpdate={update} />
      <TaskPipelineCard
        task={task}
        nodeLogs={nodeLogs}
        onChoosePipeline={() => setPipelinePickerOpen(true)}
      />
      <TaskLibraryPromptsCard task={task} libraryNodes={libraryNodes ?? []} />
    </>
  );

  return (
    <div className="flex flex-col gap-4 overflow-auto p-5 short:overflow-visible">
      <div className="px-0.5 text-caption font-extrabold uppercase tracking-wider text-text-3">
        Обзор
      </div>

      <TaskDescriptionCard task={task} />

      {task.parent_task_id && <ParentTaskCard task={task} />}

      {task.status === TaskStatus.NEW ? (
        <>
          {/* До запуска — порядок настройки: окружение, расписание, пайплайн. */}
          {environment}
          <AutoStartCard task={task} pending={updateTask.isPending} onUpdate={update} />
          {execution}
        </>
      ) : (
        <>
          {/* После запуска — сначала то, чем управляют во время работы. */}
          {execution}
          {environment}
          <AutoStartSummaryCard task={task} />
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
