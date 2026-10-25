import type { ReactNode } from "react";
import { Check, Pause, Pencil, Trash2 } from "lucide-react";
import { Checkbox } from "@/components/ui/checkbox";
import { NodeTypeIcon } from "@/components/tasks/NodeTypeIcon";
import { NODE_TYPE_LABEL } from "@/lib/labels";
import { cn } from "@/lib/utils";
import { NodeType, type TaskNodeItem } from "@/lib/types";

/** Раздел 13.1, 15.2: строка ноды задачи — включение, «пауза после», свой промт, ход выполнения. */
export function TaskNodeRow({
  taskNode,
  done,
  isCurrent,
  busy,
  onToggleEnabled,
  onTogglePause,
  onEdit,
  onDelete,
}: {
  taskNode: TaskNodeItem;
  done: boolean;
  isCurrent: boolean;
  /** Запрос по составу нод ещё не завершён. */
  busy: boolean;
  onToggleEnabled: (isEnabled: boolean) => void;
  onTogglePause: (pauseAfter: boolean) => void;
  onEdit: () => void;
  onDelete: () => void;
}) {
  // Раздел 13.1: после `clear_context` пайплайн продолжается в новой сессии — паузы нет.
  const pausable = taskNode.node_type !== NodeType.CLEAR_CONTEXT;
  const customEditable = taskNode.is_custom && taskNode.editable;
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
        <NodeTypeIcon
          type={taskNode.node_type}
          className="size-[15px] shrink-0 text-text-2"
        />
        <div className="min-w-0 flex-1">
          <div className="truncate text-note font-bold" title={taskNode.name}>
            {taskNode.name}
          </div>
          <div
            className={cn(
              "truncate text-caption font-bold uppercase tracking-wide",
              taskNode.is_custom ? "text-accent" : "text-text-3",
            )}
          >
            {taskNode.is_custom ? "свой промт" : NODE_TYPE_LABEL[taskNode.node_type]}
          </div>
        </div>
      </label>
      {customEditable && (
        <>
          <RowIconButton
            label={`Изменить промт ${taskNode.name}`}
            disabled={busy}
            onClick={onEdit}
          >
            <Pencil className="size-3.5" />
          </RowIconButton>
          <RowIconButton
            label={`Удалить промт ${taskNode.name}`}
            disabled={busy}
            onClick={onDelete}
          >
            <Trash2 className="size-3.5" />
          </RowIconButton>
        </>
      )}
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
      {done && (
        <Check className="size-3.5 shrink-0 text-success" aria-label="выполнено" />
      )}
    </div>
  );
}

function RowIconButton({
  label,
  disabled,
  onClick,
  children,
}: {
  label: string;
  disabled: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      disabled={disabled}
      onClick={onClick}
      className="touch-hit flex size-6 shrink-0 items-center justify-center rounded-md text-text-3 hover:text-text disabled:opacity-50"
    >
      {children}
    </button>
  );
}
