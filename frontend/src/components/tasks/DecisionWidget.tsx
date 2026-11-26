import { useState } from "react";
import { ArrowLeft, Send } from "lucide-react";
import { toast } from "sonner";
import { Textarea } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { PlanCard } from "@/components/tasks/PlanCard";
import { useSubmitDecision } from "@/hooks/useTasks";
import { errorMessage } from "@/lib/errors";
import { cn } from "@/lib/utils";
import type { NodeLog } from "@/lib/types";
import { CUSTOM_ANSWER_OPTION } from "@/lib/userInput";

const PREVIOUS_QUESTION_OPTION = "previous_question";

/**
 * Универсальный виджет выбора (раздел 9.6 ТЗ) — единый механизм для
 * `plan_review`, вопросов агента и подтверждения действий («Разрешить» /
 * «Запретить»): все они перехватываются одним callback'ом разрешений SDK на
 * бэкенде, поэтому здесь тоже не разные UI, а один компонент, ветвящийся по
 * `pending_options`. Вопрос показывается всегда — без него варианты ответа
 * непонятны.
 */
export function DecisionWidget({ taskId, log }: { taskId: string; log: NodeLog }) {
  const submitDecision = useSubmitDecision(taskId);
  const [comment, setComment] = useState("");
  const [openAnswer, setOpenAnswer] = useState("");
  const options = (log.pending_options ?? []).filter((option) => option.id !== PREVIOUS_QUESTION_OPTION);
  const previous = log.pending_options?.find((option) => option.id === PREVIOUS_QUESTION_OPTION);
  const isPlan = Boolean(log.pending_plan_text);

  function submit(optionId: string, feedbackText?: string) {
    submitDecision.mutate(
      {
        node_log_id: log.id,
        decision_id: log.pending_decision_id ?? undefined,
        option_id: optionId,
        feedback_text: feedbackText || undefined,
      },
      {
        onSuccess: () => {
          setComment("");
          setOpenAnswer("");
        },
        onError: (error) => {
          toast.error(errorMessage(error, "Не удалось отправить решение"));
        },
      },
    );
  }

  return (
    <div className="flex max-w-[640px] flex-col gap-3">
      {log.pending_plan_text && <PlanCard text={log.pending_plan_text} />}

      {log.pending_question && (
        <div className="rounded-[14px] border border-border bg-surface px-3.5 py-2.5 text-body-lg leading-relaxed">
          {log.pending_question}
        </div>
      )}

      {options.length > 0 ? (
        <div className="flex flex-col gap-2">
          {options.map((option, index) => (
            <button
              key={option.id}
              type="button"
              disabled={submitDecision.isPending}
              onClick={() => submit(option.id, comment)}
              className={cn(
                "touch-target rounded-xl border-[1.5px] border-border bg-surface px-4 py-3 text-left text-body-lg font-bold text-text disabled:opacity-50 short:py-1.5",
                index === 0 && "border-accent bg-accent-tint text-accent-hov",
              )}
            >
              {option.label}
            </button>
          ))}
          <Textarea
            placeholder={
              isPlan
                ? "Комментарий к решению — для «Доработать план» опишите, что изменить…"
                : "Комментарий к варианту или свой ответ…"
            }
            rows={2}
            value={comment}
            onChange={(event) => setComment(event.target.value)}
          />
          {!isPlan && (
            <div>
              <Button
                size="sm"
                variant="secondary"
                disabled={!comment.trim() || submitDecision.isPending}
                onClick={() => submit(CUSTOM_ANSWER_OPTION, comment.trim())}
              >
                <Send className="size-4" /> Ответить своим текстом
              </Button>
            </div>
          )}
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
              const answer = openAnswer.trim();
              if (previous && answer === PREVIOUS_QUESTION_OPTION) {
                submit(CUSTOM_ANSWER_OPTION, answer);
              } else {
                submit(answer);
              }
            }}
          >
            <Send className="size-4" />
          </Button>
        </div>
      )}
      {previous && (
        <div>
          <Button
            size="sm"
            variant="secondary"
            disabled={submitDecision.isPending}
            onClick={() => submit(previous.id)}
          >
            <ArrowLeft className="size-4" /> {previous.label}
          </Button>
        </div>
      )}
    </div>
  );
}
