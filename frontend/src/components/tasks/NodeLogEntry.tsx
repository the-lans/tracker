import { MessageBubble } from "@/components/tasks/MessageBubble";
import { ScriptOutputBlock } from "@/components/tasks/ScriptOutputBlock";
import { DecisionWidget } from "@/components/tasks/DecisionWidget";
import { NodeLogStatus, type NodeLog } from "@/lib/types";

export function NodeLogEntry({ taskId, log }: { taskId: string; log: NodeLog }) {
  const isScript = log.script_stdout !== null || log.script_exit_code !== null;
  const isAwaitingDecision = log.status === NodeLogStatus.AWAITING_DECISION;

  return (
    <div className="flex flex-col gap-3">
      {log.rendered_prompt && !isScript && <MessageBubble role="user" text={log.rendered_prompt} />}
      {isScript && <ScriptOutputBlock stdout={log.script_stdout} exitCode={log.script_exit_code} />}
      {log.llm_output_text && <MessageBubble role="llm" text={log.llm_output_text} />}
      {log.status === NodeLogStatus.FAILED && (
        <MessageBubble
          role="llm"
          danger
          text={`Ошибка выполнения (попытка ${log.attempt_number})`}
        />
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
