import { useEffect, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { wsUrl } from "@/lib/apiClient";
import type { Task, TaskStatusEvent } from "@/lib/types";

const RECONNECT_DELAY_MS = 3000;

/**
 * Подписка на `/ws/tasks/{id}/status` (раздел 18.1 ТЗ) — при получении
 * события со сменой статуса точечно обновляет TanStack Query кэш задачи и
 * список задач, без опроса вручную. Переподключается с фиксированной
 * задержкой при разрыве (закрытие сокета — сеть/перезапуск backend — не
 * обязательно означает, что сессия недействительна).
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
      socket = new WebSocket(wsUrl(`/ws/tasks/${taskId}/status`));
      socket.onmessage = (event: MessageEvent<string>) => {
        try {
          const payload = JSON.parse(event.data) as TaskStatusEvent;
          queryClient.setQueryData<Task | undefined>(["tasks", "detail", taskId], (prev) =>
            prev ? { ...prev, status: payload.status } : prev,
          );
          void queryClient.invalidateQueries({ queryKey: ["tasks", "list"] });
          void queryClient.invalidateQueries({ queryKey: ["tasks", taskId, "node-logs"] });
        } catch {
          // неожиданный формат сообщения — игнорируем, следующее событие поправит состояние
        }
      };
      socket.onclose = (event) => {
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
