import { FileText, GitBranch, ScrollText, Sparkles, Terminal } from "lucide-react";
import { NodeType } from "@/lib/types";

const ICONS: Record<NodeType, typeof FileText> = {
  [NodeType.PLAIN_PROMPT]: FileText,
  [NodeType.SLASH_COMMAND]: Terminal,
  [NodeType.SCRIPT]: ScrollText,
  [NodeType.CLEAR_CONTEXT]: GitBranch,
  [NodeType.PLAN_PROMPT]: Sparkles,
};

export function NodeTypeIcon({ type, className }: { type: NodeType; className?: string }) {
  const Icon = ICONS[type];
  return <Icon className={className} />;
}

export const NODE_TYPE_LABEL: Record<NodeType, string> = {
  [NodeType.PLAIN_PROMPT]: "Обычный промт",
  [NodeType.SLASH_COMMAND]: "Слэш-команда",
  [NodeType.SCRIPT]: "Скрипт",
  [NodeType.CLEAR_CONTEXT]: "Очистить контекст",
  [NodeType.PLAN_PROMPT]: "Режим планирования",
};
