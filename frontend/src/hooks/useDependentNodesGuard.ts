import { useState } from "react";
import { toast } from "sonner";
import { errorMessage } from "@/lib/errors";
import type { NodeDependent } from "@/lib/types";
import type { PendingNodeDisable } from "@/components/tasks/dependentNodes.types";

/** Раздел 13.3, 15.2: перед отключением ноды — предупреждение, если на её
 * вывод ссылаются последующие активные ноды. Отключить всё равно можно. */
export function useDependentNodesGuard() {
  const [pending, setPending] = useState<PendingNodeDisable | null>(null);

  async function guard(
    nodeName: string,
    loadDependents: () => Promise<NodeDependent[]>,
    proceed: () => void,
  ) {
    try {
      const dependents = await loadDependents();
      if (dependents.length === 0) {
        proceed();
        return;
      }
      setPending({ nodeName, dependents, proceed });
    } catch (error) {
      toast.error(errorMessage(error, "Не удалось проверить зависимые ноды"));
    }
  }

  function confirm() {
    pending?.proceed();
    setPending(null);
  }

  return { pending, guard, confirm, cancel: () => setPending(null) };
}
