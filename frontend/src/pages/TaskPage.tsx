import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import { TaskStatusBadge } from "@/components/tasks/TaskStatusBadge";
import { TaskOverviewPanel } from "@/components/tasks/TaskOverviewPanel";
import { TaskChatFeed } from "@/components/tasks/TaskChatFeed";
import { TaskControlButtons } from "@/components/tasks/TaskControlButtons";
import { RemoteControlButton } from "@/components/tasks/RemoteControlButton";
import { useTask, useTaskNodeLogs } from "@/hooks/useTasks";
import { useTaskStatusSocket } from "@/hooks/useTaskStatusSocket";
import { cn } from "@/lib/utils";

export function TaskPage() {
  const { taskId } = useParams<{ taskId: string }>();
  const { data: task, isLoading } = useTask(taskId);
  const { data: nodeLogs } = useTaskNodeLogs(taskId);
  const [mobileTab, setMobileTab] = useState<"overview" | "dialogue">("dialogue");
  useTaskStatusSocket(taskId);

  if (isLoading || !task) {
    return (
      <div className="flex h-full items-center justify-center text-text-3">
        {isLoading ? "Загрузка задачи…" : "Задача не найдена"}
      </div>
    );
  }


  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-3.5 border-b border-border bg-surface px-4 py-3 lg:px-7">
        <Link
          to="/"
          className="flex touch-target size-8 shrink-0 items-center justify-center rounded-[9px] border border-border text-text-2"
        >
          <ArrowLeft className="size-4" />
        </Link>
        <div className="min-w-0">
          <div className="font-mono text-[12px] font-bold text-text-3">{task.code}</div>
          <div className="truncate text-[16px] font-extrabold tracking-tight">{task.title}</div>
        </div>
        <TaskStatusBadge status={task.status} />
        <TaskControlButtons task={task} />
        <RemoteControlButton task={task} />
      </div>

      <div className="flex border-b border-border xl:hidden">
        <button
          type="button"
          onClick={() => setMobileTab("overview")}
          className={cn(
            "flex-1 touch-target border-b-2 border-transparent py-2.5 text-[13px] font-bold text-text-2",
            mobileTab === "overview" && "border-accent text-accent",
          )}
        >
          Обзор
        </button>
        <button
          type="button"
          onClick={() => setMobileTab("dialogue")}
          className={cn(
            "flex-1 touch-target border-b-2 border-transparent py-2.5 text-[13px] font-bold text-text-2",
            mobileTab === "dialogue" && "border-accent text-accent",
          )}
        >
          Диалог
        </button>
      </div>

      <div className="flex min-h-0 flex-1 xl:flex-row">
        <div
          className={cn(
            "min-h-0 w-full overflow-auto border-border bg-surface xl:block xl:w-[420px] xl:shrink-0 xl:border-r",
            mobileTab === "overview" ? "block" : "hidden",
          )}
        >
          <TaskOverviewPanel task={task} nodeLogs={nodeLogs ?? []} />
        </div>
        <div className={cn("min-h-0 min-w-0 flex-1 xl:flex", mobileTab === "dialogue" ? "flex" : "hidden")}>
          <TaskChatFeed taskId={task.id} taskStatus={task.status} nodeLogs={nodeLogs ?? []} />
        </div>
      </div>
    </div>
  );
}
