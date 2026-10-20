import type { NodeLog } from "@/lib/types";

/** Варианты решения по плану (раздел 9.3) — на случай записи без `pending_options`. */
const PLAN_DECISION_LABEL: Record<string, string> = {
  accept_auto: "Принять план и продолжить автоматически",
  accept_default: "Принять план, подтверждать каждое действие",
  revise: "Доработать план",
};

const AUTO_ACCEPT_ID = "accept_auto";

export interface UserInputView {
  text: string;
  /** План принят переключателем `auto_accept_plan`, а не пользователем (раздел 9.2). */
  automatic: boolean;
}

/**
 * Читаемый вид `node_logs.user_input_text`: бэкенд хранит выбранный вариант
 * первой строкой, а комментарий к нему — со второй (`encode_decision`).
 * Ответ на вопрос без вариантов хранится целиком, как ввёл пользователь.
 */
export function describeUserInput(log: NodeLog): UserInputView {
  const raw = log.user_input_text ?? "";
  const options = log.pending_options ?? [];
  const [optionId = "", ...rest] = raw.split("\n");
  const feedback = rest.join("\n").trim();

  const label =
    options.find((option) => option.id === optionId)?.label ??
    (log.pending_plan_text ? PLAN_DECISION_LABEL[optionId] : undefined);
  if (!label) return { text: raw, automatic: false };

  const automatic = optionId === AUTO_ACCEPT_ID && options.length === 0 && !feedback;
  if (automatic) return { text: "План принят автоматически", automatic };
  return { text: feedback ? `${label}\n\n${feedback}` : label, automatic: false };
}
