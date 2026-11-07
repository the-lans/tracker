import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/apiClient";
import { taskKeys } from "@/hooks/useTasks";
import type { ManualRequest, NodeType } from "@/lib/types";

export interface TaskCommand {
  id: string;
  name: string;
  slash_name: string;
  argument_hint: string | null;
  description: string | null;
  node_type: NodeType;
  revision: number;
}

export function useTaskCommands(taskId: string, prefix: string, enabled = true) {
  return useQuery({
    queryKey: ["task-commands", taskId, prefix],
    enabled,
    staleTime: 0,
    queryFn: () => api.get<TaskCommand[]>(`/tasks/${taskId}/commands`, { prefix }),
  });
}

export function useRunTaskCommand(taskId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: { invocation: string; client_request_id: string }) =>
      api.post<ManualRequest>(`/tasks/${taskId}/commands/run`, body),
    onSuccess: () => { void client.invalidateQueries({ queryKey: taskKeys.manualQueue(taskId) }); },
  });
}

export function useCommandPreview(taskId: string) {
  return useMutation({
    mutationFn: (invocation: string) =>
      api.post<{ rendered_text: string }>(`/tasks/${taskId}/commands/preview`, { invocation }),
  });
}
