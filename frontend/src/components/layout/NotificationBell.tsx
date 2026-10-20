import { Link } from "react-router-dom";
import { Bell } from "lucide-react";
import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import { useAwaitingDecisionCount, useTasks } from "@/hooks/useTasks";
import { TaskStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

/** Раздел 18.3: постоянный счётчик задач, ожидающих решения, + быстрый
 * доступ к ним из любого раздела приложения. */
export function NotificationBell() {
  const { data: awaitingCount } = useAwaitingDecisionCount();
  const { data: awaitingInput } = useTasks(TaskStatus.AWAITING_INPUT);
  const { data: planReview } = useTasks(TaskStatus.PLAN_REVIEW);
  const awaitingTasks = [...(awaitingInput ?? []), ...(planReview ?? [])];
  const count = awaitingCount?.count ?? 0;

  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger asChild>
        <button
          type="button"
          className="relative flex touch-target size-9 items-center justify-center rounded-md border border-border bg-surface text-text-2"
          aria-label="Задачи, ожидающие решения"
        >
          <Bell className="size-[17px]" />
          {count > 0 && (
            <span className="absolute -right-0.5 -top-0.5 size-2.5 rounded-full border-2 border-surface bg-danger" />
          )}
        </button>
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content
          align="end"
          sideOffset={8}
          className={cn(
            "z-50 w-80 rounded-lg border border-border bg-surface p-2 shadow-xl",
          )}
        >
          <div className="px-2 py-1.5 text-small font-bold text-text-2">
            Ожидают решения ({count})
          </div>
          {awaitingTasks.length === 0 && (
            <div className="px-2 py-3 text-body text-text-3">Нет задач, ожидающих решения</div>
          )}
          {awaitingTasks.slice(0, 8).map((task) => (
            <DropdownMenu.Item key={task.id} asChild>
              <Link
                to={`/tasks/${task.id}`}
                className="block rounded-md px-2 py-2 text-body font-semibold text-text hover:bg-surface-2"
              >
                <span className="mr-2 font-mono text-caption text-text-3">{task.code}</span>
                {task.title}
              </Link>
            </DropdownMenu.Item>
          ))}
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}
