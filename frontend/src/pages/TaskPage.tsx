import { useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import { TaskJiraLink } from "@/components/tasks/TaskJiraLink";
import { TaskStatusMenu } from "@/components/tasks/TaskStatusMenu";
import { TaskOverviewPanel } from "@/components/tasks/TaskOverviewPanel";
import { TaskChatFeed } from "@/components/tasks/TaskChatFeed";
import { TaskLogsPanel } from "@/components/tasks/TaskLogsPanel";
import { type MobileTaskTab, TaskMobileTabs } from "@/components/tasks/TaskMobileTabs";
import { TaskWorkspaceTabs, type WorkspaceView } from "@/components/tasks/TaskWorkspaceTabs";
import { TaskControlButtons } from "@/components/tasks/TaskControlButtons";
import { TaskDayMarks } from "@/components/tasks/TaskDayMarks";
import { RemoteControlButton } from "@/components/tasks/RemoteControlButton";
import { RemoteControlNotice } from "@/components/tasks/RemoteControlNotice";
import { TaskLlmAccountBadge } from "@/components/tasks/TaskLlmAccountBadge";
import { TaskLimitWaitBanner } from "@/components/tasks/TaskLimitWaitBanner";
import { bridgeViewOf } from "@/components/tasks/taskStatusMeta";
import { REMOTE_CONTROL_STATUS_LABEL } from "@/lib/labels";
import { RemoteControlStatus } from "@/lib/types";
import { useTask, useTaskNodeLogs } from "@/hooks/useTasks";
import { useTaskStatusSocket } from "@/hooks/useTaskStatusSocket";
import { useNoteBelowButtons } from "@/hooks/useNoteBelowButtons";
import { cn } from "@/lib/utils";

export function TaskPage() {
  const { taskId } = useParams<{ taskId: string }>();
  const { data: task, isLoading } = useTask(taskId);
  const { data: nodeLogs } = useTaskNodeLogs(taskId);
  const [mobileTab, setMobileTab] = useState<MobileTaskTab>("dialogue");
  useTaskStatusSocket(taskId);
  // Надпись о просмотре: под кнопками, пока строка аккаунта слева не подступила к ней, иначе — под аккаунтом.
  const leftRef = useRef<HTMLDivElement>(null);
  const buttonsRef = useRef<HTMLDivElement>(null);
  const measureRef = useRef<HTMLSpanElement>(null);
  const noteBelow = useNoteBelowButtons(
    leftRef,
    buttonsRef,
    measureRef,
    `${task?.title}:${task?.current_llm_account_id ?? task?.llm_account_id}:${task?.status}`,
  );

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
  const bridgeView = bridgeViewOf(task);
  const remoteControlNote = REMOTE_CONTROL_STATUS_LABEL[RemoteControlStatus.UNAVAILABLE];

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
        <div ref={leftRef} className="min-w-0 flex-1 basis-56">
          {/* Отметки дня переносятся на свою строку, а не сжимают код и статус. */}
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <span className="max-w-full break-all font-mono text-small font-bold text-text-3">{task.code}</span>
            <TaskStatusMenu task={task} />
            <TaskDayMarks task={task} />
          </div>
          <div className="flex items-center gap-2">
            <div
              className="min-w-0 truncate text-title font-extrabold tracking-tight xl:text-heading 2xl:text-display"
              title={task.title}
            >
              {task.title}
            </div>
            <TaskJiraLink task={task} />
          </div>
          {/* Под названием: отступ от него; тесно — надпись о просмотре на своей строке под аккаунтом.
              На телефоне эти строки стоят слева от кнопок (см. ниже). */}
          <div className="mt-1 empty:hidden max-sm:hidden">
            <TaskLlmAccountBadge task={task} />
            {bridgeView === "unavailable" && !noteBelow && (
              <p className="text-caption text-text-3">{remoteControlNote}</p>
            )}
          </div>
        </div>
        {/* Телефон (до 640 px): строка на всю ширину — аккаунт и надпись слева, кнопки справа:
            так они не занимают отдельной высоты. */}
        <div
          ref={buttonsRef}
          className="ml-auto flex flex-col items-end gap-1 max-sm:w-full max-sm:flex-row max-sm:items-center max-sm:gap-3"
        >
          <div className="min-w-0 flex-1 empty:hidden sm:hidden">
            <TaskLlmAccountBadge task={task} />
            {bridgeView === "unavailable" && (
              <p className="truncate text-caption text-text-3">{remoteControlNote}</p>
            )}
          </div>
          <div className="flex flex-wrap items-center justify-end gap-2 max-sm:shrink-0">
            <TaskControlButtons task={task} />
            {bridgeView === "reconnect" && <RemoteControlButton task={task} />}
          </div>
          {bridgeView === "unavailable" && noteBelow && (
            // Шире кнопок — выступает влево, ширину колонки кнопок не меняет.
            <div className="flex w-0 min-w-full justify-end max-sm:hidden">
              <span className="whitespace-nowrap text-caption text-text-3">{remoteControlNote}</span>
            </div>
          )}
        </div>
        {/* Замер ширины надписи: вне потока и экрана, не влияет на раскладку. */}
        <span
          ref={measureRef}
          aria-hidden
          className="pointer-events-none invisible fixed left-[-9999px] top-0 whitespace-nowrap text-caption"
        >
          {remoteControlNote}
        </span>
        {bridgeView === "reconnect" && <RemoteControlNotice />}
        <TaskLimitWaitBanner task={task} />
      </div>

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
          {workspaceView === "logs" ? (
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
