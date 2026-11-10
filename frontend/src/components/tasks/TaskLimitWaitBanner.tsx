import { Hourglass } from "lucide-react";
import { TaskStatus, type Task } from "@/lib/types";
import { formatResetTime } from "@/lib/utils";

/**
 * Раздел 15.2, 19.7: задача ждёт сброса лимита — все LLM-аккаунты автора на
 * пороге. После сброса она вернётся в прежний статус и продолжит ту же ноду.
 */
export function TaskLimitWaitBanner({ task }: { task: Task }) {
  if (task.status !== TaskStatus.AWAITING_LIMIT) return null;
  const until = task.limit_wait_until;
  return (
    <div
      role="status"
      className="flex basis-full items-start gap-2 rounded-lg border border-warning-border bg-warning-tint px-3 py-2 text-note text-warning-text"
    >
      <Hourglass className="mt-0.5 size-3.5 shrink-0" />
      <div>
        <p>
          Все LLM-аккаунты на пороге — задача продолжит{" "}
          {until ? `в ${formatResetTime(until)}` : "после сброса лимита"}
        </p>
        {task.limit_wait_from_status === TaskStatus.PAUSED && (
          <p>После сброса задача встанет на паузу</p>
        )}
      </div>
    </div>
  );
}
