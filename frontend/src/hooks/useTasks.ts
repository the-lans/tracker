import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/apiClient";
import type {
  BindPipelineRequest,
  DecisionRequest,
  ManualRequest,
  NodeDependent,
  NodeLog,
  Task,
  TaskCreateRequest,
  TaskDuplicateRequest,
  TaskLibraryPrompt,
  TaskLibraryPromptItem,
  TaskNodeItem,
  TaskRepository,
  TaskUpdateRequest,
} from "@/lib/types";

const taskKeys = {
  all: ["tasks"] as const,
  list: (statusFilter?: string) => ["tasks", "list", statusFilter ?? "all"] as const,
  detail: (id: string) => ["tasks", "detail", id] as const,
  nodeLogs: (id: string) => ["tasks", id, "node-logs"] as const,
  repositories: (id: string) => ["tasks", id, "repositories"] as const,
  nodes: (id: string) => ["tasks", id, "nodes"] as const,
  libraryPrompts: (id: string) => ["tasks", id, "library-prompts"] as const,
  manualQueue: (id: string) => ["tasks", id, "manual-queue"] as const,
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
/** Раздел 14.2: «Дублировать задачу» из `done` — новая задача с копией настроек. */
export function useDuplicateTask(taskId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: TaskDuplicateRequest) => api.post<Task>(`/tasks/${taskId}/duplicate`, body),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: taskKeys.all });
    },
  });
}

/** Раздел 14.2, 14.3: действия над завершённой/упавшей задачей, возвращающие её. */
function useTaskLifecycleAction(taskId: string, action: "cleanup-repositories" | "clear-context") {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<Task>(`/tasks/${taskId}/${action}`),
    onSuccess: (task) => {
      queryClient.setQueryData(taskKeys.detail(taskId), task);
      void queryClient.invalidateQueries({ queryKey: taskKeys.all });
    },
  });
}

export function useCleanupRepositories(taskId: string) {
  return useTaskLifecycleAction(taskId, "cleanup-repositories");
}

export function useClearContext(taskId: string) {
  return useTaskLifecycleAction(taskId, "clear-context");
}

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
    mutationFn: (body: BindPipelineRequest) => api.post<Task>(`/tasks/${taskId}/pipeline`, body),
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
      void queryClient.invalidateQueries({ queryKey: taskKeys.manualQueue(taskId) });
    },
  });
}

export function useAddLibraryPrompt(taskId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (nodeId: string) =>
      api.post<TaskLibraryPrompt>(`/tasks/${taskId}/library-prompts`, { node_id: nodeId }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: taskKeys.libraryPrompts(taskId) });
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
      void queryClient.invalidateQueries({ queryKey: taskKeys.libraryPrompts(taskId) });
      void queryClient.invalidateQueries({ queryKey: taskKeys.manualQueue(taskId) });
    },
  });
}

export function useCancelManualRequest(taskId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (requestId: string) => api.delete(`/tasks/${taskId}/manual-queue/${requestId}`),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: taskKeys.nodeLogs(taskId) });
      void queryClient.invalidateQueries({ queryKey: taskKeys.manualQueue(taskId) });
    },
  });
}

/** Раздел 7.3: кнопка ■ — отмена из очереди или прерывание выполняющегося запроса. */
export function useStopManualRequest(taskId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (requestId: string) =>
      api.post<void>(`/tasks/${taskId}/manual-queue/${requestId}/stop`),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: taskKeys.manualQueue(taskId) });
      void queryClient.invalidateQueries({ queryKey: taskKeys.libraryPrompts(taskId) });
    },
  });
}

/** Раздел 15.2: индикатор «В очереди» — запросы, ещё не завершённые воркером. */
export function useManualQueue(taskId: string) {
  return useQuery({
    queryKey: taskKeys.manualQueue(taskId),
    queryFn: () => api.get<ManualRequest[]>(`/tasks/${taskId}/manual-queue`),
    refetchInterval: 4_000,
  });
}

export function useTaskLibraryPrompts(taskId: string) {
  return useQuery({
    queryKey: taskKeys.libraryPrompts(taskId),
    queryFn: () => api.get<TaskLibraryPromptItem[]>(`/tasks/${taskId}/library-prompts`),
    refetchInterval: 4_000,
  });
}

export function useTaskNodes(taskId: string, enabled: boolean) {
  return useQuery({
    queryKey: taskKeys.nodes(taskId),
    queryFn: () => api.get<TaskNodeItem[]>(`/tasks/${taskId}/nodes`),
    enabled,
  });
}

/** Раздел 13.3, 15.2: какие ноды берут вывод у отключаемой — для предупреждения. */
export function useTaskNodeDependents(taskId: string) {
  return useMutation({
    mutationFn: (taskNodeId: string) =>
      api.get<NodeDependent[]>(`/tasks/${taskId}/nodes/${taskNodeId}/dependents`),
  });
}

/** Раздел 13.1, 13.2: включение/отключение ноды задачи. */
export function useSetTaskNodeEnabled(taskId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ taskNodeId, isEnabled }: { taskNodeId: string; isEnabled: boolean }) =>
      api.patch<TaskNodeItem>(`/tasks/${taskId}/nodes/${taskNodeId}`, { is_enabled: isEnabled }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: taskKeys.nodes(taskId) });
    },
  });
}

/** Раздел 14.2: пауза/продолжение/остановка исполняет воркер — статус
 * обновится с его переходом, поэтому здесь только инвалидация. */
function useTaskControl(taskId: string, action: "pause" | "resume" | "stop") {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<void>(`/tasks/${taskId}/${action}`),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: taskKeys.detail(taskId) });
    },
  });
}

export function usePauseTask(taskId: string) {
  return useTaskControl(taskId, "pause");
}

export function useResumeTask(taskId: string) {
  return useTaskControl(taskId, "resume");
}

export function useStopTask(taskId: string) {
  return useTaskControl(taskId, "stop");
}

/** Раздел 14.2: «Отменить постановку» — `queued -> new`, автозапуск выключается. */
export function useCancelQueuedTask(taskId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<Task>(`/tasks/${taskId}/cancel`),
    onSuccess: (task) => {
      queryClient.setQueryData(taskKeys.detail(taskId), task);
      void queryClient.invalidateQueries({ queryKey: taskKeys.all });
    },
  });
}
