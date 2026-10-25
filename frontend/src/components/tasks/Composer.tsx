import { useState } from "react";
import { Clock, Eye, MessageSquarePlus, Send } from "lucide-react";
import { toast } from "sonner";
import { Textarea } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { useManualQueue, useSubmitFreeformPrompt } from "@/hooks/useTasks";
import { useTemplatePreview } from "@/hooks/useTemplates";
import { SESSION_ACTIVE_STATUSES } from "@/components/tasks/taskStatusMeta";
import { errorMessage } from "@/lib/errors";
import { ManualRequestStatus, ManualRequestType, type TaskStatus } from "@/lib/types";

/** Раздел 8, 15.2: свободный параметризованный промт — отдельно от поля
 * ответа на awaiting_input/plan_review (см. `DecisionWidget`). Не привязан к
 * конкретному статусу, но принимается, только пока сессия задачи активна
 * (раздел 8.2); при занятой сессии запрос ждёт в очереди — индикатор
 * «В очереди» рядом с полем. Предпросмотр (раздел 8.2) показывает текст
 * после подстановки переменных — ровно тот, что уйдёт в сессию. */
export function Composer({
  taskId,
  taskStatus,
  hasLlmAccount,
}: {
  taskId: string;
  taskStatus: TaskStatus;
  /** Раздел 3.1: без LLM-аккаунта свободный промт выполнить некому. */
  hasLlmAccount: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const [previewText, setPreviewText] = useState<string | null>(null);
  const submitFreeform = useSubmitFreeformPrompt(taskId);
  const preview = useTemplatePreview();
  const { data: queue } = useManualQueue(taskId);
  const sessionActive = SESSION_ACTIVE_STATUSES.includes(taskStatus);
  const queuedFreeform = (queue ?? []).filter(
    (request) =>
      request.request_type === ManualRequestType.FREEFORM_PROMPT &&
      request.status === ManualRequestStatus.QUEUED,
  ).length;

  function handleTextChange(value: string) {
    setText(value);
    setPreviewText(null);
  }

  function handlePreview() {
    preview.mutate(
      { text: text.trim(), scope: "freeform", task_id: taskId },
      {
        onSuccess: (data) => setPreviewText(data.rendered_text),
        onError: (error) => {
          toast.error(errorMessage(error, "Ошибка предпросмотра"));
          setPreviewText(null);
        },
      },
    );
  }

  function handleSend() {
    if (!text.trim()) return;
    submitFreeform.mutate(text.trim(), {
      onSuccess: () => {
        toast.success("Промт поставлен в очередь");
        setText("");
        setPreviewText(null);
        setOpen(false);
      },
      onError: (error) => {
        toast.error(errorMessage(error, "Не удалось отправить промт"));
      },
    });
  }

  return (
    <div className="border-t border-border bg-surface p-3.5 short:sticky short:bottom-0 short:z-10 short:px-3 short:py-1.5">
      {queuedFreeform > 0 && (
        <div className="mb-2 flex items-center gap-1.5 text-meta font-bold text-info-text short:mb-1">
          <Clock className="size-3" />
          В очереди: {queuedFreeform}
        </div>
      )}
      {!hasLlmAccount ? (
        <div className="flex items-center gap-2 rounded-lg bg-surface-2 px-3 py-2.5 text-note text-text-3">
          <MessageSquarePlus className="size-3.5 shrink-0" />
          У задачи нет LLM-аккаунта — свободный промт выполнить некому
        </div>
      ) : !sessionActive ? (
        <div className="flex items-center gap-2 rounded-lg bg-surface-2 px-3 py-2.5 text-note text-text-3">
          <MessageSquarePlus className="size-3.5 shrink-0" />
          Свободный промт доступен, пока сессия задачи активна
        </div>
      ) : !open ? (
        <button
          type="button"
          onClick={() => setOpen(true)}
          className="flex touch-target w-full items-center gap-2 rounded-lg bg-surface-2 px-3 py-2.5 text-left text-note text-text-3 short:py-1"
        >
          <MessageSquarePlus className="size-3.5 shrink-0" />
          Свободный промт — задать вопрос сессии в любой момент
        </button>
      ) : (
        <div className="flex flex-col gap-2">
          {previewText !== null && (
            <div className="whitespace-pre-wrap rounded-lg border border-border bg-surface-2 px-3 py-2 text-note text-text-2">
              <div className="mb-1 text-caption font-extrabold uppercase tracking-wider text-text-3">
                После подстановки
              </div>
              {previewText}
            </div>
          )}
          <div className="flex items-end gap-2">
            <Textarea
              autoFocus
              rows={2}
              placeholder="Текст промта… Доступны {{task.*}}, {{session.id}}, {{env.*}}"
              value={text}
              onChange={(event) => handleTextChange(event.target.value)}
              className="flex-1"
            />
            <Button
              size="icon"
              variant="secondary"
              aria-label="Предпросмотр подстановки"
              disabled={!text.trim() || preview.isPending}
              onClick={handlePreview}
            >
              <Eye className="size-4" />
            </Button>
            <Button
              size="icon"
              aria-label="Отправить"
              disabled={!text.trim() || submitFreeform.isPending}
              onClick={handleSend}
            >
              <Send className="size-4" />
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
