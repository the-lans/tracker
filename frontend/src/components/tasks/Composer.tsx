import { useState } from "react";
import { MessageSquarePlus, Send } from "lucide-react";
import { toast } from "sonner";
import { Textarea } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { useSubmitFreeformPrompt } from "@/hooks/useTasks";
import { ApiError } from "@/lib/apiClient";

/** Раздел 8, 15.2: свободный параметризованный промт — отдельно от поля
 * ответа на awaiting_input/plan_review (см. `DecisionWidget`), доступно
 * всегда, вне зависимости от статуса задачи. */
export function Composer({ taskId }: { taskId: string }) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const submitFreeform = useSubmitFreeformPrompt(taskId);

  function handleSend() {
    if (!text.trim()) return;
    submitFreeform.mutate(text.trim(), {
      onSuccess: () => {
        toast.success("Промт поставлен в очередь");
        setText("");
        setOpen(false);
      },
      onError: (error) => {
        toast.error(error instanceof ApiError ? error.message : "Не удалось отправить промт");
      },
    });
  }

  return (
    <div className="border-t border-border bg-surface p-3.5">
      {!open ? (
        <button
          type="button"
          onClick={() => setOpen(true)}
          className="flex touch-target w-full items-center gap-2 rounded-lg bg-surface-2 px-3 py-2.5 text-left text-[12.5px] text-text-3"
        >
          <MessageSquarePlus className="size-3.5 shrink-0" />
          Свободный промт — задать вопрос сессии в любой момент
        </button>
      ) : (
        <div className="flex items-end gap-2">
          <Textarea
            autoFocus
            rows={2}
            placeholder="Текст промта…"
            value={text}
            onChange={(event) => setText(event.target.value)}
            className="flex-1"
          />
          <Button
            size="icon"
            disabled={!text.trim() || submitFreeform.isPending}
            onClick={handleSend}
          >
            <Send className="size-4" />
          </Button>
        </div>
      )}
    </div>
  );
}
