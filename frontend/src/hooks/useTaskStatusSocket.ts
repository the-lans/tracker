import { useEffect, useRef } from "react";
import { useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { wsAuthMessage, wsUrl } from "@/lib/apiClient";
import type { Task, TaskOutputStream, TaskSocketEvent } from "@/lib/types";

const RECONNECT_DELAY_MS = 3000;

// Вне префикса ["tasks"]: инвалидация задач не должна обнулять текст,
// который ещё генерируется.
const streamKey = (taskId: string) => ["task-stream", taskId] as const;

function applyEvent(queryClient: QueryClient, taskId: string, payload: TaskSocketEvent) {
  if (payload.type === "output_delta") {
    queryClient.setQueryData<TaskOutputStream>(streamKey(taskId), (prev) => ({
      ...prev,
      [payload.node_log_id]: (prev?.[payload.node_log_id] ?? "") + payload.text,
    }));
    return;
  }
  queryClient.setQueryData<Task | undefined>(["tasks", "detail", taskId], (prev) =>
    prev ? { ...prev, status: payload.status } : prev,
  );
  void queryClient.invalidateQueries({ queryKey: ["tasks", "list"] });
  // Раздел 18.3: счётчик «ждут решения» меняется вместе со статусом, не дожидаясь опроса.
  void queryClient.invalidateQueries({ queryKey: ["tasks", "awaiting-count"] });
  void queryClient.invalidateQueries({ queryKey: ["tasks", taskId, "node-logs"] });
  // Раздел 14.3: файлы, сохранённые агентом или скриптом, появляются без перезагрузки.
  void queryClient.invalidateQueries({ queryKey: ["tasks", taskId, "artifacts"] });
}

/**
 * Подписка на `/ws/tasks/{id}/status` (раздел 15.2, 18.1 ТЗ): смена статуса
 * точечно обновляет TanStack Query кэш задачи и списка, фрагменты ответа LLM
 * копятся в кэше потока (`useTaskOutputStream`). Переподключается с
 * фиксированной задержкой при разрыве (закрытие сокета — сеть/перезапуск
 * backend — не обязательно означает, что сессия недействительна).
 */
export function useTaskStatusSocket(taskId: string | undefined) {
  const queryClient = useQueryClient();
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  useEffect(() => {
    if (!taskId) return;
    let socket: WebSocket | null = null;
    let cancelled = false;

    function connect() {
      if (cancelled || !taskId) return;
      const current = new WebSocket(wsUrl(`/ws/tasks/${taskId}/status`));
      socket = current;
      current.onopen = () => current.send(wsAuthMessage());
      current.onmessage = (event: MessageEvent<string>) => {
        try {
          applyEvent(queryClient, taskId, JSON.parse(event.data) as TaskSocketEvent);
        } catch {
          // неожиданный формат сообщения — игнорируем, следующее событие поправит состояние
        }
      };
      current.onclose = (event) => {
        // 4401/4404 — токен недействителен либо задача удалена: переподключение бессмысленно.
        if (cancelled || event.code === 4401 || event.code === 4404) return;
        reconnectTimer.current = setTimeout(connect, RECONNECT_DELAY_MS);
      };
    }

    connect();

    return () => {
      cancelled = true;
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
      socket?.close();
    };
  }, [taskId, queryClient]);
}

/** Раздел 15.2: текст ответа, пришедший по сокету, пока ход ещё идёт. */
export function useTaskOutputStream(taskId: string): TaskOutputStream {
  const { data } = useQuery<TaskOutputStream>({
    queryKey: streamKey(taskId),
    queryFn: () => ({}),
    initialData: {},
    staleTime: Infinity,
  });
  return data;
}
