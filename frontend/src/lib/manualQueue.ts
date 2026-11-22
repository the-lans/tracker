import { ManualRequestStatus, ManualRequestType, type ManualRequest } from "@/lib/types";

/** Что показывает индикатор «В очереди» (раздел 7.3, 15.2). */
export interface QueueSummary {
  /** Свободные промты и команды, ждущие своей очереди. */
  queued: number;
  /** Из них обычный текст, который можно влить в идущий ход. */
  injectable: number;
  /** Влиты в ход, но агент их ещё не взял — отмена возможна. */
  injected: number;
  /** Индикатор показан: есть что ждать или что отменить. */
  shown: boolean;
}

/** Свободный текст без `/…`: слэш-команды, промты библиотеки и пересказы не вливаются. */
export function isInjectable(request: ManualRequest): boolean {
  return (
    request.status === ManualRequestStatus.QUEUED &&
    request.request_type === ManualRequestType.FREEFORM_PROMPT &&
    !request.command_name &&
    !(request.raw_prompt_text ?? "").trimStart().startsWith("/")
  );
}

export function summarizeQueue(queue: readonly ManualRequest[] | undefined): QueueSummary {
  const requests = queue ?? [];
  const queued = requests.filter(
    (request) =>
      (request.request_type === ManualRequestType.FREEFORM_PROMPT || request.command_name) &&
      request.status === ManualRequestStatus.QUEUED,
  ).length;
  const injected = requests.filter((request) => request.status === ManualRequestStatus.INJECTED).length;
  return {
    queued,
    injectable: requests.filter(isInjectable).length,
    injected,
    shown: queued > 0 || injected > 0,
  };
}
