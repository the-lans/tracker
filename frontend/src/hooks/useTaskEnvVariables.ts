import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/apiClient";
import type { TaskEnvVariable } from "@/lib/types";

const keyOf = (taskId: string) => ["tasks", taskId, "env-variables"] as const;

/** Раздел 3.1, 5, 15.2: переменные окружения уровня задачи. */
export function useTaskEnvVariables(taskId: string) {
  return useQuery({
    queryKey: keyOf(taskId),
    queryFn: () => api.get<TaskEnvVariable[]>(`/tasks/${taskId}/env-variables`),
  });
}

export function useCreateTaskEnvVariable(taskId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: { key: string; value: string }) =>
      api.post<TaskEnvVariable>(`/tasks/${taskId}/env-variables`, body),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: keyOf(taskId) }),
  });
}

export function useUpdateTaskEnvVariable(taskId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ variableId, value }: { variableId: string; value: string }) =>
      api.patch<TaskEnvVariable>(`/tasks/${taskId}/env-variables/${variableId}`, { value }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: keyOf(taskId) }),
  });
}

export function useDeleteTaskEnvVariable(taskId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (variableId: string) => api.delete(`/tasks/${taskId}/env-variables/${variableId}`),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: keyOf(taskId) }),
  });
}

/** Правило 8: значение показывается только по явному нажатию. */
export function useRevealTaskEnvVariable(taskId: string) {
  return useMutation({
    mutationFn: (variableId: string) =>
      api.get<{ value: string }>(`/tasks/${taskId}/env-variables/${variableId}/reveal`),
  });
}
