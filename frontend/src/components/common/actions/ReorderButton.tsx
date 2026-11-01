import { ArrowDown, ArrowUp } from "lucide-react";

export type MoveDirection = "up" | "down";

const MOVE_LABEL: Record<MoveDirection, string> = { up: "Переместить выше", down: "Переместить ниже" };

/** Кнопка ↑/↓ перестановки элемента списка с соседним; без соседа — неактивна. */
export function ReorderButton({
  name,
  direction,
  disabled,
  onMove,
}: {
  name: string;
  direction: MoveDirection;
  disabled: boolean;
  onMove: () => void;
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onMove}
      aria-label={`${MOVE_LABEL[direction]}: ${name}`}
      title={MOVE_LABEL[direction]}
      className="touch-target flex items-center justify-center text-text-3 hover:text-text disabled:opacity-30"
    >
      {direction === "up" ? <ArrowUp className="size-4" /> : <ArrowDown className="size-4" />}
    </button>
  );
}
