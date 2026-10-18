import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { toast } from "sonner";
import { ArrowLeft, RefreshCw } from "lucide-react";
import { TaskStatusBadge } from "@/components/tasks/TaskStatusBadge";
import { TaskOverviewPanel } from "@/components/tasks/TaskOverviewPanel";
import { TaskChatFeed } from "@/components/tasks/TaskChatFeed";
import { useTask, useTaskNodeLogs } from "@/hooks/useTasks";
import { useTaskStatusSocket } from "@/hooks/useTaskStatusSocket";
import { RemoteControlStatus } from "@/lib/types";
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

  const remoteControlDisconnected = task.remote_control_status !== RemoteControlStatus.CONNECTED;

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
        <button
          type="button"
          onClick={() =>
            toast.info(
              "Переподключение доступно через claude.ai/code — прямая ссылка на сессию пока не отдаётся API",
            )
          }
          className={cn(
            "ml-auto hidden items-center gap-2 rounded-md border px-3 py-2 text-[13px] font-bold sm:flex",
            remoteControlDisconnected
              ? "border-warning-border bg-warning-tint text-warning-text"
              : "border-border bg-surface text-text-2",
          )}
        >
          <RefreshCw className="size-3.5" />
          Переподключить сессию
        </button>
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
          <TaskChatFeed taskId={task.id} nodeLogs={nodeLogs ?? []} />
        </div>
      </div>
    </div>
  );
}
