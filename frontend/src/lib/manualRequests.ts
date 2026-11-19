import {
  ManualRequestStatus,
  ManualRequestType,
  type ManualRequest,
} from "@/lib/types";

/** Команда в очереди или выполняется; свободный промт — пока выполняется (раздел 7.3). */
export function isStoppableRequest(request: ManualRequest): boolean {
  if (request.command_name) return true;
  return (
    request.request_type === ManualRequestType.FREEFORM_PROMPT &&
    request.status === ManualRequestStatus.PROCESSING
  );
}

/**
 * Запрос, который остановит следующее нажатие «Остановить»: сначала выполняющийся,
 * затем ожидающие в порядке очереди; `null` — останавливать больше нечего.
 */
export function nextStoppableRequest(
  queue: readonly ManualRequest[],
): ManualRequest | null {
  const stoppable = queue.filter(isStoppableRequest);
  return (
    stoppable.find(
      (request) => request.status === ManualRequestStatus.PROCESSING,
    ) ??
    stoppable[0] ??
    null
  );
}

/** Подпись действия над запросом: «Остановить промт», «Отменить /review». */
export function stopRequestLabel(request: ManualRequest): string {
  const action =
    request.status === ManualRequestStatus.QUEUED ? "Отменить" : "Остановить";
  return request.command_name
    ? `${action} /${request.command_name}`
    : `${action} промт`;
}
