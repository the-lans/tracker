import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import { TaskStatusBadge } from "@/components/tasks/TaskStatusBadge";
import { TaskOverviewPanel } from "@/components/tasks/TaskOverviewPanel";
import { TaskChatFeed } from "@/components/tasks/TaskChatFeed";
import { TaskLogsPanel } from "@/components/tasks/TaskLogsPanel";
import { TaskWorkspaceTabs, type WorkspaceView } from "@/components/tasks/TaskWorkspaceTabs";
import { TaskControlButtons } from "@/components/tasks/TaskControlButtons";
import { RemoteControlButton } from "@/components/tasks/RemoteControlButton";
import { RemoteControlNotice } from "@/components/tasks/RemoteControlNotice";
import { SESSION_ACTIVE_STATUSES } from "@/components/tasks/taskStatusMeta";
import { useTask, useTaskNodeLogs } from "@/hooks/useTasks";
import { useTaskStatusSocket } from "@/hooks/useTaskStatusSocket";
import { cn } from "@/lib/utils";

export function TaskPage() {
  const { taskId } = useParams<{ taskId: string }>();
  const { data: task, isLoading } = useTask(taskId);
  const { data: nodeLogs } = useTaskNodeLogs(taskId);
  const [mobileTab, setMobileTab] = useState<"overview" | WorkspaceView>("dialogue");
  useTaskStatusSocket(taskId);

  if (isLoading || !task) {
    return (
      <div className="flex h-full items-center justify-center text-text-3">
        {isLoading ? "Загрузка задачи…" : "Задача не найдена"}
      </div>
    );
  }


  // На десктопе правая панель видна всегда; «Обзор» — только мобильная вкладка.
  const workspaceView: WorkspaceView = mobileTab === "logs" ? "logs" : "dialogue";
  const workspaceTabs = <TaskWorkspaceTabs value={workspaceView} onChange={setMobileTab} />;
  // Мост есть только у живой сессии Claude Code (раздел 6.5, 3.1).
  const hasBridge = task.llm_account_id !== null && SESSION_ACTIVE_STATUSES.includes(task.status);

  return (
    <div className="flex h-full flex-col short:h-auto">
      {/* Название занимает свою строку; кнопки переносятся под него, а не сжимают его. */}
      <div className="flex flex-wrap items-center gap-x-3.5 gap-y-2 border-b border-border bg-surface px-4 py-3 short:gap-y-1 short:py-1.5 lg:px-7">
        <Link
          to="/"
          aria-label="К списку задач"
          className="flex touch-target size-8 shrink-0 items-center justify-center rounded-[9px] border border-border text-text-2"
        >
          <ArrowLeft className="size-4" />
        </Link>
        <div className="min-w-0 flex-1 basis-56">
          <div className="flex items-center gap-2">
            <span className="font-mono text-small font-bold text-text-3">{task.code}</span>
            <TaskStatusBadge status={task.status} />
          </div>
          <div className="truncate text-title font-extrabold tracking-tight" title={task.title}>
            {task.title}
          </div>
        </div>
        <div className="ml-auto flex flex-wrap items-center justify-end gap-2">
          <TaskControlButtons task={task} />
          {hasBridge && <RemoteControlButton task={task} />}
        </div>
        {hasBridge && <RemoteControlNotice />}
      </div>

      <div className="flex border-b border-border xl:hidden">
        <button
          type="button"
          onClick={() => setMobileTab("overview")}
          className={cn(
            "flex-1 touch-target border-b-2 border-transparent py-2.5 text-body font-bold text-text-2 short:py-1",
            mobileTab === "overview" && "border-accent text-accent",
          )}
        >
          Обзор
        </button>
        <button
          type="button"
          onClick={() => setMobileTab("dialogue")}
          className={cn(
            "flex-1 touch-target border-b-2 border-transparent py-2.5 text-body font-bold text-text-2 short:py-1",
            mobileTab === "dialogue" && "border-accent text-accent",
          )}
        >
          Диалог
        </button>
        <button
          type="button"
          onClick={() => setMobileTab("logs")}
          className={cn(
            "flex-1 touch-target border-b-2 border-transparent py-2.5 text-body font-bold text-text-2 short:py-1",
            mobileTab === "logs" && "border-accent text-accent",
          )}
        >
          Логи
        </button>
      </div>

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
          {workspaceView === "logs" ? (
            <TaskLogsPanel taskId={task.id} header={workspaceTabs} />
          ) : (
            <TaskChatFeed
              taskId={task.id}
              taskStatus={task.status}
              hasLlmAccount={task.llm_account_id !== null}
              nodeLogs={nodeLogs ?? []}
              header={workspaceTabs}
            />
          )}
        </div>
      </div>
    </div>
  );
}
