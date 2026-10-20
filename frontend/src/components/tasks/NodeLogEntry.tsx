import { MessageBubble } from "@/components/tasks/MessageBubble";
import { ScriptOutputBlock } from "@/components/tasks/ScriptOutputBlock";
import { DecisionWidget } from "@/components/tasks/DecisionWidget";
import { NodeLogStatus, NodeLogTriggerType, type NodeLog } from "@/lib/types";

/** Метка источника реплики: ручной запуск (раздел 8.2), пересказ для
 * дочерней задачи и саммари родителя (раздел 3.1), автообработка конфликта
 * ребейза (раздел 14) — пайплайновая запись без ноды. */
function sourceLabelOf(log: NodeLog): string | undefined {
  if (log.trigger_type === NodeLogTriggerType.FREEFORM_MANUAL) return "отправлено вручную";
  if (log.trigger_type === NodeLogTriggerType.LIBRARY_MANUAL) return "промт из библиотеки";
  if (log.trigger_type === NodeLogTriggerType.SUMMARY_FOR_CHILD) return "пересказ для дочерней задачи";
  if (log.trigger_type === NodeLogTriggerType.PARENT_SUMMARY) return "саммари родительской задачи";
  if (log.trigger_type === NodeLogTriggerType.PIPELINE && log.node_id === null) {
    return "разрешение конфликта ребейза";
  }
  return undefined;
}

export function NodeLogEntry({
  taskId,
  log,
  streamedText,
}: {
  taskId: string;
  log: NodeLog;
  streamedText?: string;
}) {
  const isScript = log.script_stdout !== null || log.script_exit_code !== null;
  const isAwaitingDecision = log.status === NodeLogStatus.AWAITING_DECISION;
  const isSummaryNote =
    log.trigger_type === NodeLogTriggerType.PARENT_SUMMARY && log.llm_output_text === null;
  // Раздел 15.2: пока ход идёт, ответ показывается по мере генерации;
  // итоговый текст из БД заменяет его.
  const liveText = !log.llm_output_text && log.status === NodeLogStatus.RUNNING ? streamedText : undefined;

  return (
    <div className="flex flex-col gap-3">
      {log.rendered_prompt && !isScript && (
        <MessageBubble role="user" text={log.rendered_prompt} sourceLabel={sourceLabelOf(log)} />
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
        <MessageBubble role="llm" danger text="Остановлено пользователем" />
      )}
      {isAwaitingDecision && <DecisionWidget taskId={taskId} log={log} />}
      {!isAwaitingDecision && log.pending_plan_text && log.status === NodeLogStatus.SUCCESS && (
        <MessageBubble role="llm" text={`План принят.\n\n${log.pending_plan_text}`} />
      )}
      {!isAwaitingDecision && log.user_input_text && (
        <MessageBubble role="user" text={log.user_input_text.split("\n")[0] ?? log.user_input_text} />
      )}
    </div>
  );
}
