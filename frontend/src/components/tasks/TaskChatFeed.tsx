import { useEffect, useRef, useState, type ReactNode } from "react";
import { Maximize2, Minimize2 } from "lucide-react";
import { NodeLogEntry } from "@/components/tasks/NodeLogEntry";
import { Composer } from "@/components/tasks/Composer";
import { Button } from "@/components/ui/button";
import { useTaskOutputStream } from "@/hooks/useTaskStatusSocket";
import { useTaskNodes } from "@/hooks/useTasks";
import { cn } from "@/lib/utils";
import type { NodeLog, TaskStatus } from "@/lib/types";

export function TaskChatFeed({
  taskId,
  taskStatus,
  nodeLogs,
  header,
}: {
  taskId: string;
  taskStatus: TaskStatus;
  nodeLogs: NodeLog[];
  header: ReactNode;
}) {
  const [fullscreen, setFullscreen] = useState(false);
  const outputStream = useTaskOutputStream(taskId);
  const { data: taskNodes } = useTaskNodes(taskId, true);
  const nodeNames = new Map((taskNodes ?? []).map((node) => [node.node_id, node.name]));
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
        "flex min-w-0 flex-1 flex-col bg-[#fdfdfe]",
        fullscreen && "fixed inset-0 z-40 bg-bg",
      )}
    >
      <div className="flex items-center justify-between border-b border-border px-6 py-3.5">
        {header}
        <Button variant="ghost" size="icon" onClick={() => setFullscreen((prev) => !prev)}>
          {fullscreen ? <Minimize2 className="size-4" /> : <Maximize2 className="size-4" />}
        </Button>
      </div>

      <div ref={feedRef} className="flex min-h-0 flex-1 flex-col gap-4 overflow-auto px-6 py-5">
        {nodeLogs.length === 0 && (
          <div className="py-10 text-center text-[13px] text-text-3">
            История выполнения появится здесь после запуска задачи
          </div>
        )}
        {nodeLogs.map((log) => (
          <NodeLogEntry
            key={log.id}
            taskId={taskId}
            log={log}
            title={log.node_id ? nodeNames.get(log.node_id) : undefined}
            streamedText={outputStream[log.id]}
          />
        ))}
      </div>

      <Composer taskId={taskId} taskStatus={taskStatus} />
    </div>
  );
}
