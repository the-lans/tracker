import { Link, useLocation } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import { RemoteControlButton } from "@/components/tasks/RemoteControlButton";
import { RemoteControlNotice } from "@/components/tasks/RemoteControlNotice";
import { TaskControlButtons } from "@/components/tasks/TaskControlButtons";
import { TaskDayMarks } from "@/components/tasks/TaskDayMarks";
import { TaskHeaderInfo } from "@/components/tasks/TaskHeaderInfo";
import { TaskJiraLink } from "@/components/tasks/TaskJiraLink";
import { TaskLimitWaitBanner } from "@/components/tasks/TaskLimitWaitBanner";
import { TaskStatusMenu } from "@/components/tasks/TaskStatusMenu";
import { bridgeViewOf } from "@/components/tasks/taskStatusMeta";
import type { Task } from "@/lib/types";

/**
 * Шапка страницы задачи (раздел 15.2): код, статус, название, аккаунт и кнопки.
 * Название занимает свою строку, кнопки переносятся под него, а не сжимают его.
 * На телефоне (до 640 px) аккаунт стоит слева от кнопок в их строке. Надписи про
 * недоступный просмотр в claude.ai/code нет: мост через LLM-прокси не настроен (6.3).
 */
export function TaskHeader({ task }: { task: Task }) {
  const bridgeView = bridgeViewOf(task);
  const { state } = useLocation();
  const dashboardSearch = typeof state?.dashboardSearch === "string" ? state.dashboardSearch : "";

  return (
    <div className="flex flex-wrap items-center gap-x-3.5 gap-y-2 border-b border-border bg-surface px-4 py-3 short:gap-y-1 short:py-1.5 lg:px-7">
      <Link
        to={{ pathname: "/", search: dashboardSearch }}
        replace
        aria-label="К списку задач"
        className="flex touch-target size-8 shrink-0 items-center justify-center rounded-[9px] border border-border text-text-2"
      >
        <ArrowLeft className="size-4" />
      </Link>
      <div className="min-w-0 flex-1 basis-56">
        {/* Отметки дня переносятся на свою строку, а не сжимают код и статус. */}
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1 max-sm:gap-x-1.5">
          <span className="max-w-full break-all font-mono text-small font-bold text-text-3 max-sm:text-caption">
            {task.code}
          </span>
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
        <TaskHeaderInfo task={task} className="mt-1 max-sm:hidden" />
      </div>
      <div
        className="ml-auto flex flex-col items-end gap-1 max-sm:w-full max-sm:flex-row max-sm:items-center max-sm:gap-3"
      >
        <TaskHeaderInfo task={task} className="min-w-0 flex-1 sm:hidden" />
        <div className="flex flex-wrap items-center justify-end gap-2 max-sm:shrink-0">
          <TaskControlButtons task={task} />
          {bridgeView === "reconnect" && <RemoteControlButton task={task} />}
        </div>
      </div>
      {bridgeView === "reconnect" && <RemoteControlNotice />}
      <TaskLimitWaitBanner task={task} />
    </div>
  );
}
