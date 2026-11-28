import { useState } from "react";
import { useParams } from "react-router-dom";
import { TaskTestsPanel } from "@/components/tasks/TaskTestsPanel";
import { TaskHeader } from "@/components/tasks/TaskHeader";
import { TaskOverviewPanel } from "@/components/tasks/TaskOverviewPanel";
import { TaskChatFeed } from "@/components/tasks/TaskChatFeed";
import { TaskLogsPanel } from "@/components/tasks/TaskLogsPanel";
import { type MobileTaskTab, TaskMobileTabs } from "@/components/tasks/TaskMobileTabs";
import { TaskWorkspaceTabs, type WorkspaceView } from "@/components/tasks/TaskWorkspaceTabs";
import { useTask, useTaskNodeLogs } from "@/hooks/useTasks";
import { useTaskStatusSocket } from "@/hooks/useTaskStatusSocket";
import { cn } from "@/lib/utils";

export function TaskPage() {
  const { taskId } = useParams<{ taskId: string }>();
  const { data: task, isLoading } = useTask(taskId);
  const { data: nodeLogs } = useTaskNodeLogs(taskId);
  const [mobileTab, setMobileTab] = useState<MobileTaskTab>("dialogue");
  useTaskStatusSocket(taskId);
  if (isLoading || !task) {
    return (
      <div className="flex h-full items-center justify-center text-text-3">
        {isLoading ? "Загрузка задачи…" : "Задача не найдена"}
      </div>
    );
  }


  // На десктопе правая панель видна всегда; «Обзор» — только мобильная вкладка.
  const workspaceView: WorkspaceView = mobileTab === "overview" ? "dialogue" : mobileTab;
  const workspaceTabs = <TaskWorkspaceTabs value={workspaceView} onChange={setMobileTab} />;

  return (
    <div className="flex h-full flex-col short:h-auto">
      <TaskHeader task={task} />

      <TaskMobileTabs value={mobileTab} onChange={setMobileTab} />

      <div className="flex min-h-0 flex-1 xl:flex-row short:flex-none">
        <div
          className={cn(
            "min-h-0 w-full overflow-auto border-border bg-surface xl:block xl:w-[420px] xl:shrink-0 xl:border-r short:overflow-visible",
            mobileTab === "overview" ? "block" : "hidden",
          )}
        >
          <TaskOverviewPanel task={task} nodeLogs={nodeLogs ?? []} />
        </div>
        <div className={cn("min-h-0 min-w-0 flex-1 xl:flex", mobileTab !== "overview" ? "flex" : "hidden")}>
          {workspaceView === "tests" ? (
            <TaskTestsPanel taskId={task.id} header={workspaceTabs} />
          ) : workspaceView === "logs" ? (
            <TaskLogsPanel taskId={task.id} header={workspaceTabs} />
          ) : (
            <TaskChatFeed
              taskId={task.id}
              taskStatus={task.status}
              ownerId={task.created_by}
              manualRequestsClosed={task.manual_requests_closed ?? false}
              nodeLogs={nodeLogs ?? []}
              header={workspaceTabs}
            />
          )}
        </div>
      </div>
    </div>
  );
}
