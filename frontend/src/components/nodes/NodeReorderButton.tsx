import { ArrowDown, ArrowUp } from "lucide-react";
import { useUpdateNode } from "@/hooks/useNodes";
import type { NodeItem } from "@/lib/types";

type MoveDirection = "up" | "down";

const MOVE_LABEL: Record<MoveDirection, string> = { up: "Переместить выше", down: "Переместить ниже" };

/** Кнопка перестановки ноды пайплайна с соседней — выше или ниже. */
export function NodeReorderButton({
  node,
  neighbor,
  direction,
}: {
  node: NodeItem;
  neighbor?: NodeItem;
  direction: MoveDirection;
}) {
  const updateThis = useUpdateNode(node.id);
  const updateNeighbor = useUpdateNode(neighbor?.id ?? "");

  function swap() {
    if (!neighbor) return;
    updateThis.mutate({ order_index: neighbor.order_index ?? 0 });
    updateNeighbor.mutate({ order_index: node.order_index ?? 0 });
  }

  return (
    <button
      type="button"
      disabled={!neighbor}
      onClick={swap}
      aria-label={`${MOVE_LABEL[direction]}: ${node.name}`}
      title={MOVE_LABEL[direction]}
      className="touch-target flex items-center justify-center text-text-3 hover:text-text disabled:opacity-30"
    >
      {direction === "up" ? <ArrowUp className="size-4" /> : <ArrowDown className="size-4" />}
    </button>
  );
}
