import { useState } from "react";
import { Maximize2 } from "lucide-react";
import { MessageBubble } from "@/components/tasks/MessageBubble";
import { promptKindOf } from "@/components/tasks/messageKinds";
import { describeUserInput } from "@/lib/userInput";
import { NodeOutputSheet } from "@/components/tasks/NodeOutputSheet";
import { ScriptOutputBlock } from "@/components/tasks/ScriptOutputBlock";
import { DecisionWidget } from "@/components/tasks/DecisionWidget";
import { NodeLogStatus, NodeLogTriggerType, type NodeLog } from "@/lib/types";

/** Метка источника реплики: ручной запуск (раздел 8.2), пересказ для
 * дочерней задачи и саммари родителя (раздел 3.1), автообработка конфликта
 * ребейза (раздел 14) — пайплайновая запись без ноды. */
function sourceLabelOf(log: NodeLog): string | undefined {
  if (log.trigger_type === NodeLogTriggerType.FREEFORM_MANUAL) return "Отправлено вручную";
  if (log.trigger_type === NodeLogTriggerType.LIBRARY_MANUAL) return "Промт из библиотеки";
  if (log.trigger_type === NodeLogTriggerType.SUMMARY_FOR_CHILD) return "Пересказ для дочерней задачи";
  if (log.trigger_type === NodeLogTriggerType.PARENT_SUMMARY) return "Саммари родительской задачи";
  if (log.trigger_type === NodeLogTriggerType.PIPELINE && log.node_id === null) {
    return "Разрешение конфликта ребейза";
  }
  return undefined;
}

export function NodeLogEntry({
  taskId,
  log,
  title,
  streamedText,
}: {
  taskId: string;
  log: NodeLog;
  title?: string;
  streamedText?: string;
}) {
  const [outputOpen, setOutputOpen] = useState(false);
  // Раздел 15.2: служебная реплика помечена источником — один раз, в заголовке записи.
  const source = sourceLabelOf(log);
  const heading = source ? [source, title].filter(Boolean).join(" · ") : (title ?? "Нода пайплайна");
  const isScript = log.script_stdout !== null || log.script_exit_code !== null;
  const isAwaitingDecision = log.status === NodeLogStatus.AWAITING_DECISION;
  const isSummaryNote =
    log.trigger_type === NodeLogTriggerType.PARENT_SUMMARY && log.llm_output_text === null;
  // Раздел 15.2: пока ход идёт, ответ показывается по мере генерации;
  // итоговый текст из БД заменяет его.
  const userInput =
    !isAwaitingDecision && log.user_input_text ? describeUserInput(log) : null;
  const liveText = !log.llm_output_text && log.status === NodeLogStatus.RUNNING ? streamedText : undefined;

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between gap-2 text-caption font-bold text-text-3">
        <span className="truncate" title={heading}>
          {heading}
        </span>
        <button
          type="button"
          onClick={() => setOutputOpen(true)}
          className="touch-hit inline-flex shrink-0 items-center gap-1 hover:text-text-2"
        >
          <Maximize2 className="size-3" /> Полный вывод
        </button>
      </div>
      <NodeOutputSheet
        log={log}
        title={heading}
        open={outputOpen}
        onOpenChange={setOutputOpen}
      />
      {log.rendered_prompt && !isScript && (
        <MessageBubble
          role="user"
          text={log.rendered_prompt}
          kind={promptKindOf(log)}
        />
      )}
      {isScript && <ScriptOutputBlock stdout={log.script_stdout} exitCode={log.script_exit_code} />}
      {log.llm_output_text && <MessageBubble role="llm" text={log.llm_output_text} />}
      {liveText && <MessageBubble role="llm" text={liveText} streaming />}
      {/* Пометка «саммари недоступно» сама объясняет себя — без общей ошибки. */}
      {log.status === NodeLogStatus.FAILED && !isSummaryNote && (
        <MessageBubble
          role="llm"
          danger
          text={`Ошибка выполнения (попытка ${log.attempt_number})`}
        />
      )}
      {log.status === NodeLogStatus.STOPPED && (
        <MessageBubble role="llm" danger kind="stopped" text="Остановлено пользователем" />
      )}
      {isAwaitingDecision && <DecisionWidget taskId={taskId} log={log} />}
      {!isAwaitingDecision && log.pending_plan_text && log.status === NodeLogStatus.SUCCESS && (
        <MessageBubble role="llm" kind="plan" text={`План принят.\n\n${log.pending_plan_text}`} />
      )}
      {userInput && (
        <MessageBubble
          role={userInput.automatic ? "llm" : "user"}
          kind={userInput.automatic ? "plan" : "decision"}
          text={userInput.text}
        />
      )}
    </div>
  );
}
