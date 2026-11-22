import { useState, type ReactNode } from "react";
import { Maximize2, MessagesSquare, Minimize2 } from "lucide-react";
import { EmptyState } from "@/components/common/feedback/EmptyState";
import { NodeLogEntry } from "@/components/tasks/NodeLogEntry";
import { DateSeparator } from "@/components/tasks/DateSeparator";
import { ScrollToBottomButton } from "@/components/tasks/ScrollToBottomButton";
import { SessionEventNotice } from "@/components/tasks/SessionEventNotice";
import { Composer } from "@/components/tasks/Composer";
import { Button } from "@/components/ui/button";
import { useLlmAccounts, useLlmAvailable } from "@/hooks/useLlmAccounts";
import { useStickToBottom } from "@/hooks/useStickToBottom";
import { useTaskOutputStream } from "@/hooks/useTaskStatusSocket";
import { useTaskLibraryPrompts, useTaskNodes, useTaskSessionEvents } from "@/hooks/useTasks";
import { cn } from "@/lib/utils";
import { isAgentTurn } from "@/components/tasks/messageKinds";
import { mergeFeed, withDateSeparators } from "@/lib/chatFeed";
import { TaskStatus, type NodeLog, type NodeType } from "@/lib/types";
import { isPreLaunch } from "@/lib/taskStatusTransitions";

/** Пустая лента: что сделать, чтобы здесь появилась история. */
type EmptyFeedKind = "new" | "refining" | "queued" | "other";

const EMPTY_FEED: Record<EmptyFeedKind, { title: string; hint: string }> = {
  new: {
    title: "Задача ещё не запускалась",
    hint: "Выберите пайплайн на вкладке «Обзор» и нажмите «Запустить» в шапке задачи. Здесь появятся промты, ответы агента и вывод скриптов.",
  },
  refining: {
    title: "Обсудите задачу с агентом",
    hint: "Задайте вопрос в поле ниже — агент ответит в сессии задачи, пайплайн не запустится. «Запустить» потом продолжит ту же сессию.",
  },
  queued: {
    title: "Задача в очереди на запуск",
    hint: "Выполнение начнётся, когда освободится воркер. История появится здесь автоматически.",
  },
  other: {
    title: "Записей пока нет",
    hint: "Здесь появятся промты, ответы агента и вывод скриптов. Свободный промт можно отправить в поле ниже.",
  },
};

function emptyFeedKind(status: TaskStatus): EmptyFeedKind {
  if (status === TaskStatus.REFINING) return "refining";
  if (isPreLaunch(status)) return "new";
  return status === TaskStatus.QUEUED ? "queued" : "other";
}

export function TaskChatFeed({
  taskId,
  taskStatus,
  ownerId,
  manualRequestsClosed = false,
  nodeLogs,
  header,
}: {
  taskId: string;
  taskStatus: TaskStatus;
  /** Автор задачи — его LLM-аккаунты выполняют промты (раздел 19.2). */
  ownerId: string;
  manualRequestsClosed?: boolean;
  nodeLogs: NodeLog[];
  header: ReactNode;
}) {
  const [fullscreen, setFullscreen] = useState(false);
  const outputStream = useTaskOutputStream(taskId);
  const { data: taskNodes } = useTaskNodes(taskId, true);
  const { data: libraryPrompts } = useTaskLibraryPrompts(taskId);
  // Имена нод пайплайна и промтов библиотеки — для заголовка записи в ленте.
  const nodeNames = new Map([
    ...(libraryPrompts ?? []).map((prompt): [string, string] => [prompt.node_id, prompt.name]),
    ...(taskNodes ?? []).map((node): [string, string] => [node.node_id, node.name]),
  ]);
  const nodeTypes = new Map([
    ...(libraryPrompts ?? []).map((prompt): [string, NodeType] => [prompt.node_id, prompt.node_type]),
    ...(taskNodes ?? []).map((node): [string, NodeType] => [node.node_id, node.node_type]),
  ]);
  const { data: sessionEvents } = useTaskSessionEvents(taskId);
  const feedItems = mergeFeed(nodeLogs, sessionEvents ?? []);
  const feedEntries = withDateSeparators(feedItems);
  const { data: llmAccounts } = useLlmAccounts();
  const llmAvailable = useLlmAvailable(ownerId);
  const accountLabels = new Map((llmAccounts ?? []).map((account) => [account.id, account.label]));
  // Растущий ответ и новые реплики двигают ленту вниз, пока пользователь у её конца.
  const streamedLength = Object.values(outputStream).reduce((total, text) => total + text.length, 0);
  const {
    ref: feedRef,
    onScroll: handleFeedScroll,
    hasUnseen,
    awayFromBottom,
    scrollToBottom,
  } = useStickToBottom<HTMLDivElement>(`${feedItems.length}:${streamedLength}`);

  return (
    <div
      className={cn(
        "flex min-w-0 flex-1 flex-col bg-surface",
        fullscreen && "fixed inset-0 z-40 overflow-auto bg-bg",
      )}
    >
      {/* На широком экране высота как у шапки панели «Логи»: кнопка компактная, зона нажатия — `touch-hit`. */}
      <div className="flex items-center justify-between border-b border-border px-4 py-0.5 xl:px-6 xl:py-2">
        {header}
        <Button
          variant="ghost"
          size="icon"
          className="touch-hit ml-auto xl:size-7 xl:min-h-0! xl:min-w-0!"
          aria-label={fullscreen ? "Свернуть ленту" : "Развернуть ленту на весь экран"}
          onClick={() => setFullscreen((prev) => !prev)}
        >
          {fullscreen ? <Minimize2 className="size-4" /> : <Maximize2 className="size-4" />}
        </Button>
      </div>

      <div className="relative flex min-h-0 flex-1 flex-col">
        <div ref={feedRef} onScroll={handleFeedScroll} className="@container flex min-h-0 flex-1 flex-col gap-4 overflow-auto px-2.5 py-5 sm:px-6 short:flex-none short:gap-3 short:overflow-visible short:py-3">
          {feedItems.length === 0 && (
            <EmptyState
              icon={MessagesSquare}
              {...EMPTY_FEED[emptyFeedKind(taskStatus)]}
            />
          )}
          {feedEntries.map((entry) => {
            if (entry.type === "date") return <DateSeparator key={`date-${entry.at}`} at={entry.at} />;
            if (entry.type === "event") {
              return <SessionEventNotice key={`event-${entry.event.id}`} kind={entry.event.kind} />;
            }
            const { log } = entry;
            return (
              <NodeLogEntry
                key={log.id}
                taskId={taskId}
                log={log}
                title={
                  log.command_name
                    ? `/${log.command_name} · версия ${log.command_revision}`
                    : log.node_id
                      ? nodeNames.get(log.node_id)
                      : undefined
                }
                streamedText={outputStream[log.id]}
                isAgentTurn={isAgentTurn(log, nodeTypes)}
                accountLabel={log.llm_account_id ? accountLabels.get(log.llm_account_id) : undefined}
              />
            );
          })}
        </div>
        {(awayFromBottom || hasUnseen) && (
          <ScrollToBottomButton hasUnseen={hasUnseen} onClick={scrollToBottom} />
        )}
      </div>

      <Composer taskId={taskId} taskStatus={taskStatus} llmAvailable={llmAvailable} manualRequestsClosed={manualRequestsClosed} />
    </div>
  );
}
