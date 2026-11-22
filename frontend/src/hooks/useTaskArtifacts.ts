import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useInvalidatingMutation } from "@/hooks/useInvalidatingMutation";
import { taskKeys } from "@/hooks/useTasks";
import { api } from "@/lib/apiClient";
import type { JiraAttachmentCopy, TaskArtifact } from "@/lib/types";

const keyOf = (taskId: string) => ["tasks", taskId, "artifacts"] as const;

/** Путь артефакта в URL: каждый сегмент кодируется отдельно, "/" остаётся разделителем. */
export function artifactUrl(taskId: string, path: string): string {
  const encoded = path.split("/").map(encodeURIComponent).join("/");
  return `/tasks/${taskId}/artifacts/${encoded}`;
}

/**
 * Раздел 14.3, 15.2: артефакты задачи. ``refetchInterval`` — как часто
 * перечитывать список, пока файлы появляются без действий пользователя
 * (агент или копирование вложений Jira); `false` — только по событиям.
 */
export function useTaskArtifacts(taskId: string, refetchInterval: number | false) {
  return useQuery({
    queryKey: keyOf(taskId),
    queryFn: () => api.get<TaskArtifact[]>(`/tasks/${taskId}/artifacts`),
    refetchInterval,
  });
}

/**
 * Содержимое файла артефакта для просмотра. Не кешируется после закрытия окна
 * (``gcTime: 0``), чтобы большие файлы не копились в памяти; изменённый файл
 * (``modifiedAt``) загружается заново.
 */
export function useArtifactFile(taskId: string, path: string, modifiedAt: string, enabled: boolean) {
  return useQuery({
    queryKey: ["tasks", taskId, "artifact-file", path, modifiedAt] as const,
    queryFn: () => api.getBlob(artifactUrl(taskId, path)),
    enabled,
    gcTime: 0,
    retry: false,
  });
}

// Вложения Jira копирует фоновая задача уже после создания задачи: пока она
// идёт, статус копирования и список артефактов перечитываются часто.
export const JIRA_COPY_REFETCH_INTERVAL_MS = 3_000;

/**
 * Раздел 15.6: идёт ли копирование вложений Jira. Пока идёт — статус
 * перечитывается; когда закончилось — список артефактов перечитывается
 * последний раз, чтобы показать файлы, скопированные после прошлого опроса,
 * а задача — чтобы показать отрисованное описание: его фоновая задача
 * сохраняет в начале копирования, уже после создания задачи.
 */
export function useJiraAttachmentCopy(taskId: string, enabled: boolean) {
  const queryClient = useQueryClient();
  return useQuery({
    queryKey: ["tasks", taskId, "jira-attachments"] as const,
    queryFn: async () => {
      const copy = await api.get<JiraAttachmentCopy>(`/tasks/${taskId}/jira-attachments`);
      if (!copy.pending) {
        void queryClient.invalidateQueries({ queryKey: keyOf(taskId) });
        void queryClient.invalidateQueries({ queryKey: taskKeys.detail(taskId) });
      }
      return copy;
    },
    enabled,
    refetchInterval: (query) => (query.state.data?.pending ? JIRA_COPY_REFETCH_INTERVAL_MS : false),
  });
}

export function useUploadTaskArtifact(taskId: string) {
  return useInvalidatingMutation(
    (file: File) => api.put<TaskArtifact>(artifactUrl(taskId, file.name), file),
    [keyOf(taskId)],
  );
}

export function useDeleteTaskArtifact(taskId: string) {
  return useInvalidatingMutation(
    (path: string) => api.delete(artifactUrl(taskId, path)),
    [keyOf(taskId)],
  );
}
