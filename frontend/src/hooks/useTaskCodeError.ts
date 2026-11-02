import { useState } from "react";
import { toast } from "sonner";
import type { TaskFormValues } from "@/components/tasks/taskForm.types";
import { errorMessage, taskCodeErrorMessage } from "@/lib/errors";

/**
 * Ошибка сервера о коде задачи — под полем «Код задачи», как ошибка формата;
 * прочие ошибки сохранения — уведомлением. Ошибка снимается при правке кода.
 */
export function useTaskCodeError(fallback: string) {
  const [codeError, setCodeError] = useState<string | null>(null);

  return {
    codeError,
    onFieldsChange: (patch: Partial<TaskFormValues>) => {
      if (patch.code !== undefined) setCodeError(null);
    },
    onSaveError: (error: unknown) => {
      const message = taskCodeErrorMessage(error);
      if (message) setCodeError(message);
      else toast.error(errorMessage(error, fallback));
    },
  };
}
