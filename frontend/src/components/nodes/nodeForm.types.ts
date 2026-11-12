import { NodeType } from "@/lib/types";

/** `null` — поле пустое: backend возьмёт значение из «Системных настроек» и у новой ноды, и при правке. */
export interface NodeExecutionValues {
  timeoutSeconds: number | null;
  maxRetries: number | null;
  retryBaseDelaySeconds: number | null;
  isSkipped: boolean;
}

/** Раздел 7.6: содержимое ноды пайплайна — своё или из промта библиотеки. */
export const NodeSource = {
  OWN: "own",
  LIBRARY: "library",
} as const;
export type NodeSource = (typeof NodeSource)[keyof typeof NodeSource];

export interface LibrarySourceValue {
  source: NodeSource;
  libraryNodeId: string | null;
  /** Тип выбранного промта — его получит нода пайплайна. */
  libraryNodeType: NodeType | null;
  arguments: string;
}

/** Промты библиотеки, которые нода пайплайна может выполнить по ссылке. */
export const LINKABLE_NODE_TYPES: readonly NodeType[] = [
  NodeType.PLAIN_PROMPT,
  NodeType.SLASH_COMMAND,
  NodeType.SCRIPT,
];
