import { useState } from "react";
import { Clock, Eye, MessageSquarePlus, Send } from "lucide-react";
import { toast } from "sonner";
import { Textarea } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { useManualQueue, useSubmitFreeformPrompt } from "@/hooks/useTasks";
import { useTemplatePreview } from "@/hooks/useTemplates";
import { SESSION_ACTIVE_STATUSES } from "@/components/tasks/taskStatusMeta";
import { ApiError } from "@/lib/apiClient";
import { ManualRequestStatus, ManualRequestType, type TaskStatus } from "@/lib/types";

/** Раздел 8, 15.2: свободный параметризованный промт — отдельно от поля
 * ответа на awaiting_input/plan_review (см. `DecisionWidget`). Не привязан к
 * конкретному статусу, но принимается, только пока сессия задачи активна
 * (раздел 8.2); при занятой сессии запрос ждёт в очереди — индикатор
 * «В очереди» рядом с полем. Предпросмотр (раздел 8.2) показывает текст
 * после подстановки переменных — ровно тот, что уйдёт в сессию. */
export function Composer({ taskId, taskStatus }: { taskId: string; taskStatus: TaskStatus }) {
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
          toast.error(error instanceof ApiError ? error.message : "Ошибка предпросмотра");
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
        toast.error(error instanceof ApiError ? error.message : "Не удалось отправить промт");
      },
    });
  }

  return (
    <div className="border-t border-border bg-surface p-3.5">
      {queuedFreeform > 0 && (
        <div className="mb-2 flex items-center gap-1.5 text-[11.5px] font-bold text-info-text">
          <Clock className="size-3" />
          В очереди: {queuedFreeform}
        </div>
      )}
      {!sessionActive ? (
        <div className="flex items-center gap-2 rounded-lg bg-surface-2 px-3 py-2.5 text-[12.5px] text-text-3">
          <MessageSquarePlus className="size-3.5 shrink-0" />
          Свободный промт доступен, пока сессия задачи активна
        </div>
      ) : !open ? (
        <button
          type="button"
          onClick={() => setOpen(true)}
          className="flex touch-target w-full items-center gap-2 rounded-lg bg-surface-2 px-3 py-2.5 text-left text-[12.5px] text-text-3"
        >
          <MessageSquarePlus className="size-3.5 shrink-0" />
          Свободный промт — задать вопрос сессии в любой момент
        </button>
      ) : (
        <div className="flex flex-col gap-2">
          {previewText !== null && (
            <div className="whitespace-pre-wrap rounded-lg border border-border bg-surface-2 px-3 py-2 text-[12.5px] text-text-2">
              <div className="mb-1 text-[10.5px] font-extrabold uppercase tracking-wider text-text-3">
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
