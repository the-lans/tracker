import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/apiClient";
import type { TaskArtifact } from "@/lib/types";

const keyOf = (taskId: string) => ["tasks", taskId, "artifacts"] as const;

/** Путь артефакта в URL: каждый сегмент кодируется отдельно, "/" остаётся разделителем. */
export function artifactUrl(taskId: string, path: string): string {
  const encoded = path.split("/").map(encodeURIComponent).join("/");
  return `/tasks/${taskId}/artifacts/${encoded}`;
}

// Пока задача работает, агент сохраняет файлы и между сменами статуса.
const ACTIVE_REFETCH_INTERVAL_MS = 15_000;

/**
 * Раздел 14.3, 15.2: артефакты задачи. ``active`` — у задачи живая сессия:
 * список перечитывается периодически, а не только при смене статуса.
 */
export function useTaskArtifacts(taskId: string, active = false) {
  return useQuery({
    queryKey: keyOf(taskId),
    queryFn: () => api.get<TaskArtifact[]>(`/tasks/${taskId}/artifacts`),
    refetchInterval: active ? ACTIVE_REFETCH_INTERVAL_MS : false,
  });
}

export function useUploadTaskArtifact(taskId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (file: File) => api.put<TaskArtifact>(artifactUrl(taskId, file.name), file),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: keyOf(taskId) }),
  });
}

export function useDeleteTaskArtifact(taskId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (path: string) => api.delete(artifactUrl(taskId, path)),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: keyOf(taskId) }),
  });
}
