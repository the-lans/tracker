import { useState } from "react";
import { Send } from "lucide-react";
import { toast } from "sonner";
import { Textarea } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { PlanCard } from "@/components/tasks/PlanCard";
import { useSubmitDecision } from "@/hooks/useTasks";
import { ApiError } from "@/lib/apiClient";
import { cn } from "@/lib/utils";
import type { NodeLog } from "@/lib/types";

/**
 * Универсальный виджет выбора (раздел 9.6 ТЗ) — единый механизм для
 * `plan_review` и обычного `awaiting_input` с вариантами: оба перехватываются
 * одним и тем же callback'ом разрешений SDK на бэкенде, поэтому здесь тоже
 * не два разных UI, а один компонент, ветвящийся по `pending_options`.
 */
export function DecisionWidget({ taskId, log }: { taskId: string; log: NodeLog }) {
  const submitDecision = useSubmitDecision(taskId);
  const [comment, setComment] = useState("");
  const [openAnswer, setOpenAnswer] = useState("");
  const hasOptions = (log.pending_options?.length ?? 0) > 0;

  function submit(optionId: string, feedbackText?: string) {
    submitDecision.mutate(
      { node_log_id: log.id, option_id: optionId, feedback_text: feedbackText || undefined },
      {
        onError: (error) => {
          toast.error(error instanceof ApiError ? error.message : "Не удалось отправить решение");
        },
      },
    );
  }

  return (
    <div className="flex max-w-[640px] flex-col gap-3">
      {log.pending_plan_text && <PlanCard text={log.pending_plan_text} />}

      {!hasOptions && log.pending_question && (
        <div className="rounded-[14px] border border-border bg-surface px-3.5 py-2.5 text-[13.5px] leading-relaxed">
          {log.pending_question}
        </div>
      )}

      {hasOptions ? (
        <div className="flex flex-col gap-2">
          {log.pending_options!.map((option, index) => (
            <button
              key={option.id}
              type="button"
              disabled={submitDecision.isPending}
              onClick={() => submit(option.id, comment)}
              className={cn(
                "touch-target rounded-xl border-[1.5px] border-border bg-surface px-4 py-3 text-left text-[13.5px] font-bold text-text disabled:opacity-50",
                index === 0 && "border-accent bg-accent-tint text-accent-hov",
              )}
            >
              {option.label}
            </button>
          ))}
          <Textarea
            placeholder="Комментарий к решению (необязательно)…"
            rows={2}
            value={comment}
            onChange={(event) => setComment(event.target.value)}
          />
        </div>
      ) : (
        <div className="flex items-center gap-2">
          <Textarea
            placeholder="Ваш ответ…"
            rows={1}
            value={openAnswer}
            onChange={(event) => setOpenAnswer(event.target.value)}
            className="flex-1"
          />
          <Button
            size="icon"
            disabled={!openAnswer.trim() || submitDecision.isPending}
            onClick={() => {
              submit(openAnswer.trim());
              setOpenAnswer("");
            }}
          >
            <Send className="size-4" />
          </Button>
        </div>
      )}
    </div>
  );
}
