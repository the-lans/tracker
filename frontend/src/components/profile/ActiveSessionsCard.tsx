import { Link } from "react-router-dom";
import { Card, CardTitle } from "@/components/ui/card";
import { TaskStatusBadge } from "@/components/tasks/TaskStatusBadge";
import { useActiveSessions } from "@/hooks/useTasks";
import { RemoteControlStatus } from "@/lib/types";
import { EmptyState } from "@/components/common/feedback/EmptyState";
import { LoadingState } from "@/components/common/feedback/LoadingState";

const BRIDGE_LABEL: Record<RemoteControlStatus, string> = {
  [RemoteControlStatus.CONNECTED]: "мост подключён",
  [RemoteControlStatus.RECONNECTING]: "мост переподключается",
  [RemoteControlStatus.DISCONNECTED]: "мост отключён",
};

/** Раздел 15.1: активные сессии Claude Code задач пользователя. */
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
            className="flex min-h-11 items-center gap-2 border-t border-border py-2 first:border-t-0"
          >
            <span className="font-mono text-small font-bold text-text-3">{task.code}</span>
            <span className="min-w-0 flex-1 truncate text-body font-bold" title={task.title}>{task.title}</span>
            <span className="hidden text-caption text-text-3 sm:inline">
              {BRIDGE_LABEL[task.remote_control_status]}
            </span>
            <TaskStatusBadge status={task.status} />
          </Link>
        ))}
      </div>
    </Card>
  );
}
