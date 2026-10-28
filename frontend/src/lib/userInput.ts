import { NodeLogStatus, type NodeLog } from "@/lib/types";

/** Варианты решения по плану (раздел 9.3) — на случай записи без `pending_options`. */
const PLAN_DECISION_LABEL: Record<string, string> = {
  accept_auto: "Принять план и продолжить автоматически",
  accept_default: "Принять план, подтверждать каждое действие",
  revise: "Доработать план",
};

const AUTO_ACCEPT_ID = "accept_auto";

/** Ответ на вопрос агента своим текстом (`CUSTOM_ANSWER_OPTION` на бэкенде). */
export const CUSTOM_ANSWER_OPTION = "custom";

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
  if (optionId === CUSTOM_ANSWER_OPTION && feedback) return { text: feedback, automatic: false };

  const label =
    options.find((option) => option.id === optionId)?.label ??
    (log.pending_plan_text ? PLAN_DECISION_LABEL[optionId] : undefined);
  if (!label) return { text: raw, automatic: false };

  const automatic = optionId === AUTO_ACCEPT_ID && options.length === 0 && !feedback;
  if (automatic) return { text: "План принят автоматически", automatic };
  return { text: feedback ? `${label}\n\n${feedback}` : label, automatic: false };
}

export interface OutputAroundDecision {
  /** Ответ агента до запроса решения. */
  before: string;
  /** Ответ после решения пользователя. */
  after: string;
}

/**
 * Раздел 15.2: решение пользователя стоит в ленте там, где агент его
 * запросил. `decision_output_offset` считает символы, как Python, — по
 * кодовым точкам, а не по UTF-16 (эмодзи не рвутся). Без смещения решение
 * идёт после всего ответа.
 */
export function splitOutputAtDecision(text: string, offset: number | null): OutputAroundDecision {
  if (offset === null) return { before: text, after: "" };
  const chars = Array.from(text);
  return {
    before: chars.slice(0, offset).join("").trimEnd(),
    after: chars.slice(offset).join("").trimStart(),
  };
}

export interface TurnOutputView extends OutputAroundDecision {
  /** Ответ ещё генерируется. */
  generating: boolean;
  /** Генерируется продолжение после решения пользователя — оно ниже решения. */
  liveAfterDecision: boolean;
  /** Агент думает: генерируемая часть ответа ещё пуста. */
  thinking: boolean;
  /** Ответ увиден в потоке — после хода не сворачивается, как в CLI. */
  keepExpanded: boolean;
}

/**
 * Раздел 15.2: что показать из ответа записи. Пока ход не завершён (идёт
 * или ждёт решения), ответ — из потока; затем — итог из БД. Решение стоит
 * в точке ответа, где агент его запросил, — и в потоке, и в итоге.
 */
export function turnOutputOf(
  log: NodeLog,
  streamedText: string | undefined,
  isAgentTurn: boolean,
): TurnOutputView {
  const isRunning = log.status === NodeLogStatus.RUNNING;
  const turnOpen = isRunning || log.status === NodeLogStatus.AWAITING_DECISION;
  const finalText = log.llm_output_text;
  const output = splitOutputAtDecision(
    finalText ?? (turnOpen ? (streamedText ?? "") : ""),
    log.decision_output_offset,
  );
  const generating = finalText === null && isRunning;
  const liveAfterDecision = generating && log.decision_output_offset !== null;
  const liveSegment = liveAfterDecision ? output.after : output.before;
  return {
    ...output,
    generating,
    liveAfterDecision,
    thinking: generating && isAgentTurn && !liveSegment,
    keepExpanded: streamedText !== undefined,
  };
}
