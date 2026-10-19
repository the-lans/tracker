import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/apiClient";
import type {
  DecisionRequest,
  ManualRequest,
  NodeLog,
  Task,
  TaskCreateRequest,
  TaskLibraryPrompt,
  TaskRepository,
  TaskUpdateRequest,
} from "@/lib/types";

const taskKeys = {
  all: ["tasks"] as const,
  list: (statusFilter?: string) => ["tasks", "list", statusFilter ?? "all"] as const,
  detail: (id: string) => ["tasks", "detail", id] as const,
  nodeLogs: (id: string) => ["tasks", id, "node-logs"] as const,
  repositories: (id: string) => ["tasks", id, "repositories"] as const,
};

export function useTasks(statusFilter?: string) {
  return useQuery({
    queryKey: taskKeys.list(statusFilter),
    queryFn: () => api.get<Task[]>("/tasks", { status_filter: statusFilter }),
    refetchInterval: 15_000,
  });
}

/** Раздел 18.3: постоянный счётчик задач, ожидающих решения (для бейджа в
 * сайдбаре и колокольчика в шапке). */
export function useAwaitingDecisionCount() {
  return useQuery({
    queryKey: ["tasks", "awaiting-count"],
    queryFn: () => api.get<{ count: number }>("/tasks/awaiting-count"),
    refetchInterval: 15_000,
  });
}

export function useTask(taskId: string | undefined) {
  return useQuery({
    queryKey: taskId ? taskKeys.detail(taskId) : ["tasks", "detail", "none"],
    queryFn: () => api.get<Task>(`/tasks/${taskId}`),
    enabled: Boolean(taskId),
  });
}

export function useTaskNodeLogs(taskId: string | undefined) {
  return useQuery({
    queryKey: taskId ? taskKeys.nodeLogs(taskId) : ["tasks", "none", "node-logs"],
    queryFn: () => api.get<NodeLog[]>(`/tasks/${taskId}/node-logs`),
    enabled: Boolean(taskId),
    refetchInterval: 4_000,
  });
}

export function useCreateTask() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: TaskCreateRequest) => api.post<Task>("/tasks", body),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: taskKeys.all });
    },
  });
}

export function useTaskRepositories(taskId: string) {
  return useQuery({
    queryKey: taskKeys.repositories(taskId),
    queryFn: () => api.get<TaskRepository[]>(`/tasks/${taskId}/repositories`),
  });
}

export function useUpdateTask(taskId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: TaskUpdateRequest) => api.patch<Task>(`/tasks/${taskId}`, body),
    onSuccess: (task) => {
      queryClient.setQueryData(taskKeys.detail(taskId), task);
      void queryClient.invalidateQueries({ queryKey: taskKeys.all });
    },
  });
}

/** Раздел 14.2: «Перезапустить с текущей ноды» — упавшая нода выполняется заново. */
export function useRestartTask(taskId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<Task>(`/tasks/${taskId}/restart`),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: taskKeys.detail(taskId) });
      void queryClient.invalidateQueries({ queryKey: taskKeys.all });
    },
  });
}

export function useBindPipeline(taskId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (pipelineId: string) =>
      api.post<Task>(`/tasks/${taskId}/pipeline`, { pipeline_id: pipelineId }),
    onSuccess: (task) => {
      queryClient.setQueryData(taskKeys.detail(taskId), task);
      void queryClient.invalidateQueries({ queryKey: taskKeys.all });
    },
  });
}

export function useStartTask(taskId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<Task>(`/tasks/${taskId}/start`),
    onSuccess: (task) => {
      queryClient.setQueryData(taskKeys.detail(taskId), task);
      void queryClient.invalidateQueries({ queryKey: taskKeys.all });
    },
  });
}

export function useSubmitDecision(taskId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: DecisionRequest) => api.post<void>(`/tasks/${taskId}/decision`, body),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: taskKeys.nodeLogs(taskId) });
      void queryClient.invalidateQueries({ queryKey: taskKeys.detail(taskId) });
    },
  });
}

export function useSubmitFreeformPrompt(taskId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (rawPromptText: string) =>
      api.post<ManualRequest>(`/tasks/${taskId}/freeform`, { raw_prompt_text: rawPromptText }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: taskKeys.nodeLogs(taskId) });
    },
  });
}

export function useAddLibraryPrompt(taskId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (nodeId: string) =>
      api.post<TaskLibraryPrompt>(`/tasks/${taskId}/library-prompts`, { node_id: nodeId }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["tasks", taskId, "library-prompts"] });
    },
  });
}

export function useRunLibraryPrompt(taskId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (taskLibraryPromptId: string) =>
      api.post<ManualRequest>(`/tasks/${taskId}/library-prompts/${taskLibraryPromptId}/run`),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: taskKeys.nodeLogs(taskId) });
    },
  });
}

export function useCancelManualRequest(taskId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (requestId: string) => api.delete(`/tasks/${taskId}/manual-queue/${requestId}`),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: taskKeys.nodeLogs(taskId) });
    },
  });
}
