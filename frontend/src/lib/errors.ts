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
