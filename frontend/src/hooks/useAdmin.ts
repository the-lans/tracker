import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/apiClient";
import { JIRA_SERVER_KEY } from "@/hooks/useProfile";
import type {
  ActiveCeleryTask,
  AllowedEmail,
  AppLog,
  AppLogLevel,
  Integrations,
  IntegrationsUpdate,
  LibraryUsage,
  NodeLogStatus,
  NodeRun,
  PeriodicTask,
  PeriodicTaskUpdateRequest,
  SystemSettings,
  User,
  UserUpdateRequest,
} from "@/lib/types";

const USERS_KEY = ["admin", "users"] as const;
const ALLOWED_EMAILS_KEY = ["admin", "allowed-emails"] as const;
const PERIODIC_TASKS_KEY = ["admin", "periodic-tasks"] as const;

export function useUsers(options: { enabled?: boolean } = {}) {
  return useQuery({
    queryKey: USERS_KEY,
    queryFn: () => api.get<User[]>("/users"),
    enabled: options.enabled ?? true,
  });
}

export function useUpdateUser(userId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: UserUpdateRequest) => api.patch<User>(`/users/${userId}`, body),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: USERS_KEY }),
  });
}

export function useAllowedEmails() {
  return useQuery({
    queryKey: ALLOWED_EMAILS_KEY,
    queryFn: () => api.get<AllowedEmail[]>("/allowed-emails"),
  });
}

export function useCreateAllowedEmail() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (email: string) => api.post<AllowedEmail>("/allowed-emails", { email }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ALLOWED_EMAILS_KEY }),
  });
}

export function useDeleteAllowedEmail() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (allowedEmailId: string) => api.delete(`/allowed-emails/${allowedEmailId}`),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ALLOWED_EMAILS_KEY }),
  });
}

export function usePeriodicTasks() {
  return useQuery({
    queryKey: PERIODIC_TASKS_KEY,
    queryFn: () => api.get<PeriodicTask[]>("/periodic-tasks"),
    refetchInterval: 20_000,
  });
}

export function useUpdatePeriodicTask(periodicTaskId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: PeriodicTaskUpdateRequest) =>
      api.patch<PeriodicTask>(`/periodic-tasks/${periodicTaskId}`, body),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: PERIODIC_TASKS_KEY }),
  });
}

export function useRunPeriodicTaskNow() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (periodicTaskId: string) =>
      api.post<void>(`/periodic-tasks/${periodicTaskId}/run-now`),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: PERIODIC_TASKS_KEY }),
  });
}

export interface AppLogFilters {
  level?: AppLogLevel;
  source?: string;
  taskId?: string;
  /** Раздел 15.5: задача по коду RR-XXXXX. */
  taskCode?: string;
  createdFrom?: string;
  createdTo?: string;
}

export function useAppLogs(filters: AppLogFilters) {
  return useQuery({
    queryKey: ["admin", "app-logs", filters],
    queryFn: () =>
      api.get<AppLog[]>("/app-logs", {
        level: filters.level,
        source: filters.source,
        task_id: filters.taskId,
        task_code: filters.taskCode,
        created_from: filters.createdFrom,
        created_to: filters.createdTo,
      }),
    refetchInterval: 15_000,
  });
}

/** Раздел 13.4: сводка выполнения нод по всем задачам. */
export function useNodeRuns(filters: { status?: NodeLogStatus }) {
  return useQuery({
    queryKey: ["admin", "node-runs", filters],
    queryFn: () => api.get<NodeRun[]>("/monitoring/node-runs", { status: filters.status }),
    refetchInterval: 15_000,
  });
}

/** Раздел 15.5: активные Celery-задачи по всем пользователям. */
export function useActiveCeleryTasks() {
  return useQuery({
    queryKey: ["admin", "celery-tasks"],
    queryFn: () => api.get<ActiveCeleryTask[]>("/monitoring/celery-tasks"),
    refetchInterval: 10_000,
  });
}

const SYSTEM_SETTINGS_KEY = ["system-settings"] as const;

/** Раздел 15.5: читается и формой ноды, поэтому вне ключей админки. */
export function useSystemSettings() {
  return useQuery({
    queryKey: SYSTEM_SETTINGS_KEY,
    queryFn: () => api.get<SystemSettings>("/system-settings"),
  });
}

export function useUpdateSystemSettings() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: SystemSettings) => api.put<SystemSettings>("/system-settings", body),
    onSuccess: (settings) => queryClient.setQueryData(SYSTEM_SETTINGS_KEY, settings),
  });
}

const INTEGRATIONS_KEY = ["admin", "integrations"] as const;

/** Раздел 15.5, 15.6: адрес и токен GitLab, адрес Jira — только администратору. */
export function useIntegrations() {
  return useQuery({
    queryKey: INTEGRATIONS_KEY,
    queryFn: () => api.get<Integrations>("/system-settings/integrations"),
  });
}

export function useUpdateIntegrations() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: IntegrationsUpdate) =>
      api.put<Integrations>("/system-settings/integrations", body),
    onSuccess: (integrations) => {
      queryClient.setQueryData(INTEGRATIONS_KEY, integrations);
      void queryClient.invalidateQueries({ queryKey: JIRA_SERVER_KEY });
    },
  });
}

export function useLibraryUsage() {
  return useQuery({
    queryKey: ["admin", "library-usage"],
    queryFn: () => api.get<LibraryUsage[]>("/nodes/library-usage"),
  });
}
