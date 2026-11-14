import type { LibraryLinkValue, OwnNodeContent } from "@/components/nodes/nodeForm.types";
import { NodeType } from "@/lib/types";

export const PROMPT_TYPES: readonly NodeType[] = [NodeType.PLAIN_PROMPT, NodeType.PLAN_PROMPT];

/**
 * Раздел 7.6: нода со ссылкой хранит только её — текст, скрипт и гайд берутся
 * из библиотеки. Тип ноды backend всё равно берёт у промта; без выбранного
 * промта форма не сохраняется.
 */
export function linkedContentPayload(link: LibraryLinkValue) {
  return {
    node_type: link.libraryNodeType ?? NodeType.PLAIN_PROMPT,
    prompt_template: null,
    command_invocation: null,
    script_language: null,
    script_content: null,
    guide_url: null,
    library_node_id: link.libraryNodeId,
    library_arguments: link.arguments.trim() || null,
    library_plan_mode: link.libraryNodeType === NodeType.PLAIN_PROMPT && (link.planMode ?? false),
  };
}

/** Своё содержимое ноды: поля чужих типов не отправляются, гайд — только у «Обычного промта». */
export function ownContentPayload(content: OwnNodeContent, { isPipeline }: { isPipeline: boolean }) {
  const { nodeType } = content;
  return {
    node_type: nodeType,
    prompt_template: PROMPT_TYPES.includes(nodeType) ? content.promptTemplate : null,
    command_invocation: nodeType === NodeType.SLASH_COMMAND ? content.commandInvocation : null,
    script_language: nodeType === NodeType.SCRIPT ? content.scriptLanguage : null,
    script_content: nodeType === NodeType.SCRIPT ? content.scriptContent : null,
    guide_url: nodeType === NodeType.PLAIN_PROMPT ? content.guideUrl || null : null,
    ...(isPipeline ? { library_node_id: null, library_arguments: null } : {}),
  };
}
