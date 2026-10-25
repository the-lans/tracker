import { Link } from "react-router-dom";
import { Card, CardTitle } from "@/components/ui/card";
import { TaskStatusBadge } from "@/components/tasks/TaskStatusBadge";
import { useActiveSessions } from "@/hooks/useTasks";
import { RemoteControlStatus, type Task } from "@/lib/types";
import { EmptyState } from "@/components/common/feedback/EmptyState";
import { LoadingState } from "@/components/common/feedback/LoadingState";

const BRIDGE_LABEL: Record<RemoteControlStatus, string> = {
  [RemoteControlStatus.CONNECTED]: "мост подключён",
  [RemoteControlStatus.RECONNECTING]: "мост переподключается",
  [RemoteControlStatus.DISCONNECTED]: "мост отключён",
};

/** У задачи без LLM-аккаунта нет моста `/remote-control` (раздел 3.1). */
function bridgeLabel(task: Task): string {
  if (task.llm_account_id === null) return "без моста — нет LLM-аккаунта";
  return BRIDGE_LABEL[task.remote_control_status];
}

/** Раздел 15.1: активные сессии Claude Code задач пользователя со статусом моста. */
export function ActiveSessionsCard() {
  const { data: tasks, isLoading } = useActiveSessions();

  return (
    <Card>
      <CardTitle>
        <span>Активные сессии</span>
        {tasks && <span>{tasks.length}</span>}
      </CardTitle>
      {isLoading && <LoadingState />}
      {!isLoading && (tasks ?? []).length === 0 && (
        <EmptyState
          compact
          title="Сейчас ни одна ваша задача не выполняется"
          hint="Здесь появятся задачи с открытой сессией Claude: в работе, на паузе или в ожидании вашего решения."
        />
      )}
      <div className="flex flex-col">
        {(tasks ?? []).map((task) => (
          <Link
            key={task.id}
            to={`/tasks/${task.id}`}
            className="flex min-h-11 flex-wrap items-center gap-x-2 gap-y-0.5 border-t border-border py-2 first:border-t-0"
          >
            <span className="font-mono text-small font-bold text-text-3">{task.code}</span>
            <span className="min-w-0 flex-1 truncate text-body font-bold" title={task.title}>{task.title}</span>
            <TaskStatusBadge status={task.status} />
            {/* На узком экране статус моста уходит на свою строку, а не скрывается. */}
            <span className="basis-full text-caption text-text-3 sm:basis-auto">
              {bridgeLabel(task)}
            </span>
          </Link>
        ))}
      </div>
    </Card>
  );
}
