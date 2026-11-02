import { ReorderButton, type MoveDirection } from "@/components/common/actions/ReorderButton";
import { useUpdateNode } from "@/hooks/useNodes";
import type { NodeItem } from "@/lib/types";

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

  return <ReorderButton name={node.name} direction={direction} disabled={!neighbor} onMove={swap} />;
}
