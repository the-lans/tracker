import {
  BookOpen,
  Bot,
  ClipboardCheck,
  CircleStop,
  FileInput,
  FileOutput,
  GitMerge,
  Reply,
  SquareSlash,
  TriangleAlert,
  User,
  Workflow,
  type LucideIcon,
} from "lucide-react";
import { NodeLogTriggerType, type NodeLog } from "@/lib/types";

/** Вид реплики в ленте: кто или что за ней стоит — по нему выбирается значок кружка. */
export type MessageKind =
  | "pipeline"
  | "slash"
  | "manual"
  | "library"
  | "parent-summary"
  | "child-summary"
  | "rebase"
  | "decision"
  | "agent"
  | "plan"
  | "error"
  | "stopped";

export const MESSAGE_KINDS: Record<MessageKind, { icon: LucideIcon; title: string }> = {
  pipeline: { icon: Workflow, title: "Промт ноды пайплайна" },
  slash: { icon: SquareSlash, title: "Слэш-команда" },
  manual: { icon: User, title: "Отправлено вручную" },
  library: { icon: BookOpen, title: "Промт из библиотеки" },
  "parent-summary": { icon: FileInput, title: "Саммари родительской задачи" },
  "child-summary": { icon: FileOutput, title: "Пересказ для дочерней задачи" },
  rebase: { icon: GitMerge, title: "Разрешение конфликта ребейза" },
  decision: { icon: Reply, title: "Решение пользователя" },
  agent: { icon: Bot, title: "Ответ агента" },
  plan: { icon: ClipboardCheck, title: "Принятый план" },
  error: { icon: TriangleAlert, title: "Ошибка выполнения" },
  stopped: { icon: CircleStop, title: "Остановлено" },
};

/** Вид реплики-запроса по источнику записи `node_logs` (раздел 13.4). */
export function promptKindOf(log: NodeLog): MessageKind {
  switch (log.trigger_type) {
    case NodeLogTriggerType.FREEFORM_MANUAL:
      return "manual";
    case NodeLogTriggerType.LIBRARY_MANUAL:
      return "library";
    case NodeLogTriggerType.PARENT_SUMMARY:
      return "parent-summary";
    case NodeLogTriggerType.SUMMARY_FOR_CHILD:
      return "child-summary";
    default:
      if (log.node_id === null) return "rebase";
      return log.rendered_prompt?.trimStart().startsWith("/") ? "slash" : "pipeline";
  }
}
