import type { NodeDependent } from "@/lib/types";

/** Отключение ноды, ожидающее подтверждения (раздел 13.3, 15.2). */
export interface PendingNodeDisable {
  nodeName: string;
  dependents: NodeDependent[];
  proceed: () => void;
}
