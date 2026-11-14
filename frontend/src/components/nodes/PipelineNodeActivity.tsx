import { Checkbox } from "@/components/ui/checkbox";
import { useUpdateNode } from "@/hooks/useNodes";
import { toastError } from "@/lib/errors";
import type { NodeItem } from "@/lib/types";

/** Активность по умолчанию при добавлении пайплайна в задачу. */
export function PipelineNodeActivity({ node }: { node: NodeItem }) {
  const updateNode = useUpdateNode(node.id);

  return (
    <label
      className="flex min-h-11 shrink-0 items-center gap-2.5 text-small font-semibold"
      title="Активна по умолчанию"
    >
      <Checkbox
        checked={!node.is_skipped}
        disabled={updateNode.isPending}
        aria-label={`Активна по умолчанию: ${node.name}`}
        onCheckedChange={(checked) =>
          updateNode.mutate(
            { is_skipped: checked !== true },
            { onError: toastError("Не удалось изменить активность ноды") },
          )
        }
      />
      <span className="hidden sm:inline">Активна</span>
    </label>
  );
}
