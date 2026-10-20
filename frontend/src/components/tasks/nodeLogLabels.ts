import { NodeLogStatus, NodeLogTriggerType } from "@/lib/types";

/** Раздел 13.4: источник записи истории — для фильтров и таблицы «Логи». */
export const TRIGGER_LABEL: Record<NodeLogTriggerType, string> = {
  [NodeLogTriggerType.PIPELINE]: "Пайплайн",
  [NodeLogTriggerType.LIBRARY_MANUAL]: "Промт из библиотеки",
  [NodeLogTriggerType.FREEFORM_MANUAL]: "Свободный промт",
  [NodeLogTriggerType.SUMMARY_FOR_CHILD]: "Пересказ для дочерней",
  [NodeLogTriggerType.PARENT_SUMMARY]: "Саммари родителя",
};

export const STATUS_LABEL: Record<NodeLogStatus, string> = {
  [NodeLogStatus.PENDING]: "ожидает",
  [NodeLogStatus.RUNNING]: "выполняется",
  [NodeLogStatus.AWAITING_DECISION]: "ждёт решения",
  [NodeLogStatus.SUCCESS]: "успешно",
  [NodeLogStatus.FAILED]: "ошибка",
  [NodeLogStatus.STOPPED]: "остановлено",
};

export const STATUS_TONE: Record<NodeLogStatus, "danger" | "warning" | "info" | "success" | "neutral"> = {
  [NodeLogStatus.PENDING]: "neutral",
  [NodeLogStatus.RUNNING]: "info",
  [NodeLogStatus.AWAITING_DECISION]: "warning",
  [NodeLogStatus.SUCCESS]: "success",
  [NodeLogStatus.FAILED]: "danger",
  [NodeLogStatus.STOPPED]: "warning",
};
