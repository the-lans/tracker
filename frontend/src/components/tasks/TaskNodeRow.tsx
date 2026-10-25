import { Check, Pause } from "lucide-react";
import { Checkbox } from "@/components/ui/checkbox";
import { NodeTypeIcon } from "@/components/tasks/NodeTypeIcon";
import { NODE_TYPE_LABEL } from "@/lib/labels";
import { cn } from "@/lib/utils";
import { NodeType, type TaskNodeItem } from "@/lib/types";

/** Раздел 13.1, 15.2: строка ноды задачи — включение, отметка «пауза после», ход выполнения. */
export function TaskNodeRow({
  taskNode,
  done,
  isCurrent,
  busy,
  onToggleEnabled,
  onTogglePause,
}: {
  taskNode: TaskNodeItem;
  done: boolean;
  isCurrent: boolean;
  /** Запрос по составу нод ещё не завершён. */
  busy: boolean;
  onToggleEnabled: (isEnabled: boolean) => void;
  onTogglePause: (pauseAfter: boolean) => void;
}) {
  // Раздел 13.1: после `clear_context` пайплайн продолжается в новой сессии — паузы нет.
  const pausable = taskNode.node_type !== NodeType.CLEAR_CONTEXT;
  return (
    <div
      className={cn(
        "flex items-center gap-2.5 border-t border-border py-2 first:border-t-0",
        isCurrent && "-mx-2 rounded-lg border-t-0 bg-accent-tint px-2",
        !taskNode.is_enabled && "text-text-3",
      )}
    >
      <label className="flex min-w-0 flex-1 items-center gap-2.5">
        <Checkbox
          checked={taskNode.is_enabled}
          disabled={!taskNode.editable || busy}
          aria-label={`Включить ноду ${taskNode.name}`}
          onCheckedChange={(checked) => onToggleEnabled(checked === true)}
        />
        <NodeTypeIcon type={taskNode.node_type} className="size-[15px] shrink-0 text-text-2" />
        <div className="min-w-0 flex-1 truncate text-note font-bold" title={taskNode.name}>
          {taskNode.name}
        </div>
      </label>
      {pausable && (
        <button
          type="button"
          aria-label={`Пауза после ноды ${taskNode.name}`}
          aria-pressed={taskNode.pause_after}
          title="Остановиться после этой ноды, чтобы продолжить диалог"
          disabled={busy}
          onClick={() => onTogglePause(!taskNode.pause_after)}
          className={cn(
            "touch-hit flex size-6 shrink-0 items-center justify-center rounded-md text-text-3 disabled:opacity-50",
            taskNode.pause_after && "bg-accent-tint text-accent",
          )}
        >
          <Pause className="size-3.5" />
        </button>
      )}
      {done ? (
        <Check className="size-3.5 shrink-0 text-success" aria-label="выполнено" />
      ) : (
        <div className="text-caption font-bold uppercase tracking-wide text-text-3">
          {NODE_TYPE_LABEL[taskNode.node_type]}
        </div>
      )}
    </div>
  );
}
