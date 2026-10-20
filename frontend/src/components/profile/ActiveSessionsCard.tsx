import { Link } from "react-router-dom";
import { Card, CardTitle } from "@/components/ui/card";
import { TaskStatusBadge } from "@/components/tasks/TaskStatusBadge";
import { useActiveSessions } from "@/hooks/useTasks";
import { RemoteControlStatus } from "@/lib/types";

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
      {isLoading && <div className="text-[13px] text-text-3">Загрузка…</div>}
      {!isLoading && (tasks ?? []).length === 0 && (
        <div className="text-[13px] text-text-3">Сейчас ни одна ваша задача не выполняется</div>
      )}
      <div className="flex flex-col">
        {(tasks ?? []).map((task) => (
          <Link
            key={task.id}
            to={`/tasks/${task.id}`}
            className="flex items-center gap-2 border-t border-border py-2 first:border-t-0"
          >
            <span className="font-mono text-[12px] font-bold text-text-3">{task.code}</span>
            <span className="min-w-0 flex-1 truncate text-[13px] font-bold">{task.title}</span>
            <span className="hidden text-[11px] text-text-3 sm:inline">
              {BRIDGE_LABEL[task.remote_control_status]}
            </span>
            <TaskStatusBadge status={task.status} />
          </Link>
        ))}
      </div>
    </Card>
  );
}
