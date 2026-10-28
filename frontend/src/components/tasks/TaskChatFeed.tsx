import { useEffect, useRef, useState, type ReactNode } from "react";
import { Maximize2, MessagesSquare, Minimize2 } from "lucide-react";
import { EmptyState } from "@/components/common/feedback/EmptyState";
import { NodeLogEntry } from "@/components/tasks/NodeLogEntry";
import { Composer } from "@/components/tasks/Composer";
import { Button } from "@/components/ui/button";
import { useTaskOutputStream } from "@/hooks/useTaskStatusSocket";
import { useTaskLibraryPrompts, useTaskNodes } from "@/hooks/useTasks";
import { cn } from "@/lib/utils";
import { isAgentTurn } from "@/components/tasks/messageKinds";
import { TaskStatus, type NodeLog, type NodeType } from "@/lib/types";

/** Пустая лента: что сделать, чтобы здесь появилась история. */
const EMPTY_FEED: Record<"new" | "queued" | "other", { title: string; hint: string }> = {
  new: {
    title: "Задача ещё не запускалась",
    hint: "Выберите пайплайн на вкладке «Обзор» и нажмите «Запустить» в шапке задачи. Здесь появятся промты, ответы агента и вывод скриптов.",
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

export function TaskChatFeed({
  taskId,
  taskStatus,
  hasLlmAccount,
  nodeLogs,
  header,
}: {
  taskId: string;
  taskStatus: TaskStatus;
  hasLlmAccount: boolean;
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
  const feedRef = useRef<HTMLDivElement>(null);
  const previousLength = useRef(0);

  useEffect(() => {
    if (nodeLogs.length !== previousLength.current) {
      feedRef.current?.scrollTo({ top: feedRef.current.scrollHeight, behavior: "smooth" });
      previousLength.current = nodeLogs.length;
    }
  }, [nodeLogs.length]);

  return (
    <div
      className={cn(
        "flex min-w-0 flex-1 flex-col bg-surface",
        fullscreen && "fixed inset-0 z-40 overflow-auto bg-bg",
      )}
    >
      <div className="flex items-center justify-between border-b border-border px-4 py-0.5 xl:px-6 xl:py-3.5">
        {header}
        <Button
          variant="ghost"
          size="icon"
          className="ml-auto"
          aria-label={fullscreen ? "Свернуть ленту" : "Развернуть ленту на весь экран"}
          onClick={() => setFullscreen((prev) => !prev)}
        >
          {fullscreen ? <Minimize2 className="size-4" /> : <Maximize2 className="size-4" />}
        </Button>
      </div>

      <div ref={feedRef} className="flex min-h-0 flex-1 flex-col gap-4 overflow-auto px-6 py-5 short:flex-none short:gap-3 short:overflow-visible short:py-3">
        {nodeLogs.length === 0 && (
          <EmptyState
            icon={MessagesSquare}
            {...EMPTY_FEED[taskStatus === TaskStatus.NEW || taskStatus === TaskStatus.QUEUED ? taskStatus : "other"]}
          />
        )}
        {nodeLogs.map((log) => (
          <NodeLogEntry
            key={log.id}
            taskId={taskId}
            log={log}
            title={log.node_id ? nodeNames.get(log.node_id) : undefined}
            streamedText={outputStream[log.id]}
            isLlmTurn={isAgentTurn(log, nodeTypes)}
          />
        ))}
      </div>

      <Composer taskId={taskId} taskStatus={taskStatus} hasLlmAccount={hasLlmAccount} />
    </div>
  );
}
