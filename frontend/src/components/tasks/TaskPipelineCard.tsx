import { Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { TaskNodesCard } from "@/components/tasks/TaskNodesCard";
import { TaskStatus, type NodeLog, type Task } from "@/lib/types";

/** Ноды пайплайна задачи или выбор пайплайна, пока он не привязан (раздел 13.1). */
export function TaskPipelineCard({
  task,
  nodeLogs,
  onChoosePipeline,
}: {
  task: Task;
  nodeLogs: NodeLog[];
  onChoosePipeline: () => void;
}) {
  if (task.pipeline_id) {
    return <TaskNodesCard task={task} nodeLogs={nodeLogs} onChangePipeline={onChoosePipeline} />;
  }
  return (
    <Card>
      <div className="mb-2 text-body text-text-2">Пайплайн не выбран</div>
      {task.status === TaskStatus.NEW && (
        <Button size="sm" variant="secondary" onClick={onChoosePipeline}>
          <Plus className="size-4" />
          Выбрать пайплайн
        </Button>
      )}
    </Card>
  );
}
