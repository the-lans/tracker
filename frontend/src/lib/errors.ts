import { toast } from "sonner";

import { ApiError } from "@/lib/apiClient";

/** Текст ошибки для пользователя: сообщение API или запасной текст. */
export function errorMessage(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.message : fallback;
}

/** Обработчик `onError` мутации: тост с текстом ошибки. */
export function toastError(fallback: string): (error: unknown) => void {
  return (error) => toast.error(errorMessage(error, fallback));
}

/** Раздел 3.1: ошибки API о коде задачи — формат и занятый код. */
const TASK_CODE_ERROR_CODES = new Set(["invalid_task_code", "task_code_taken"]);

/** Текст ошибки для поля «Код задачи» или `null`, если ошибка о другом. */
export function taskCodeErrorMessage(error: unknown): string | null {
  return error instanceof ApiError && TASK_CODE_ERROR_CODES.has(error.code) ? error.message : null;
}
