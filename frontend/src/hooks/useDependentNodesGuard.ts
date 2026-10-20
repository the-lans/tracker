import { useState } from "react";
import { toast } from "sonner";
import { ApiError } from "@/lib/apiClient";
import type { NodeDependent } from "@/lib/types";

export interface PendingNodeDisable {
  nodeName: string;
  dependents: NodeDependent[];
  proceed: () => void;
}

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
      toast.error(error instanceof ApiError ? error.message : "Не удалось проверить зависимые ноды");
    }
  }

  function confirm() {
    pending?.proceed();
    setPending(null);
  }

  return { pending, guard, confirm, cancel: () => setPending(null) };
}
