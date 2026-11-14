import { PauseAfterButton } from "@/components/common/actions/PauseAfterButton";
import { useUpdateNode } from "@/hooks/useNodes";
import { toastError } from "@/lib/errors";
import { NodeType, type NodeItem } from "@/lib/types";

export function PipelineNodePause({ node }: { node: NodeItem }) {
  const updateNode = useUpdateNode(node.id);
  if (node.node_type === NodeType.CLEAR_CONTEXT) return null;

  return (
    <PauseAfterButton
      name={node.name}
      pressed={node.pause_after}
      disabled={updateNode.isPending}
      onChange={(pauseAfter) => updateNode.mutate(
        { pause_after: pauseAfter },
        { onError: toastError("Не удалось изменить паузу после ноды") },
      )}
    />
  );
}
