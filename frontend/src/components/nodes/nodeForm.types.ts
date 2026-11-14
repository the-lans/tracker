import { NodeType, type ScriptLanguage } from "@/lib/types";


/**
 * Раздел 7.6: «Промт из библиотеки» — тип в форме ноды пайплайна. Нода
 * хранит ссылку на промт и получает его тип, своего `node_type` для ссылки нет.
 */
export const LIBRARY_PROMPT_TYPE = "library_prompt";
export type NodeFormType = NodeType | typeof LIBRARY_PROMPT_TYPE;

export interface LibraryLinkValue {
  libraryNodeId: string | null;
  /** Тип выбранного промта — его получит нода пайплайна. */
  libraryNodeType: NodeType | null;
  arguments: string;
  planMode?: boolean;
}

/** Промты библиотеки, которые нода пайплайна может выполнить по ссылке. */
export const LINKABLE_NODE_TYPES: readonly NodeType[] = [
  NodeType.PLAIN_PROMPT,
  NodeType.SLASH_COMMAND,
  NodeType.SCRIPT,
];

/** Поля содержимого ноды, заполненные в форме вручную. */
export interface OwnNodeContent {
  nodeType: NodeType;
  promptTemplate: string;
  commandInvocation: string;
  scriptLanguage: ScriptLanguage;
  scriptContent: string;
  guideUrl: string;
}
