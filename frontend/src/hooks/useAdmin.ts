import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useInvalidatingMutation } from "@/hooks/useInvalidatingMutation";
import { api } from "@/lib/apiClient";
import { JIRA_SERVER_KEY } from "@/hooks/useProfile";
import {
  BackupRunStatus,
  type ActiveCeleryTask,
  type AllowedEmail,
  type BackupConnectionCheck,
  type BackupSettings,
  type BackupSettingsUpdate,
  type AppLog,
  type AppLogLevel,
  type Integrations,
  type IntegrationsUpdate,
  type LibraryUsage,
  type NodeLogStatus,
  type NodeRun,
  type PeriodicTask,
  type PeriodicTaskUpdateRequest,
  type ProxyState,
  type SystemSettings,
  type User,
  type UserUpdateRequest,
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
  return useInvalidatingMutation(
    (body: UserUpdateRequest) => api.patch<User>(`/users/${userId}`, body),
    [USERS_KEY],
  );
}

export function useAllowedEmails() {
  return useQuery({
    queryKey: ALLOWED_EMAILS_KEY,
    queryFn: () => api.get<AllowedEmail[]>("/allowed-emails"),
  });
}

export function useCreateAllowedEmail() {
  return useInvalidatingMutation(
    (email: string) => api.post<AllowedEmail>("/allowed-emails", { email }),
    [ALLOWED_EMAILS_KEY],
  );
}

export function useDeleteAllowedEmail() {
  return useInvalidatingMutation(
    (allowedEmailId: string) => api.delete(`/allowed-emails/${allowedEmailId}`),
    [ALLOWED_EMAILS_KEY],
  );
}

export function usePeriodicTasks() {
  return useQuery({
    queryKey: PERIODIC_TASKS_KEY,
    queryFn: () => api.get<PeriodicTask[]>("/periodic-tasks"),
    refetchInterval: 20_000,
  });
}

export function useUpdatePeriodicTask(periodicTaskId: string) {
  return useInvalidatingMutation(
    (body: PeriodicTaskUpdateRequest) =>
      api.patch<PeriodicTask>(`/periodic-tasks/${periodicTaskId}`, body),
    [PERIODIC_TASKS_KEY],
  );
}

export function useRunPeriodicTaskNow() {
  return useInvalidatingMutation(
    (periodicTaskId: string) => api.post<void>(`/periodic-tasks/${periodicTaskId}/run-now`),
    [PERIODIC_TASKS_KEY],
  );
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
    onSuccess: (settings) => {
      queryClient.setQueryData(SYSTEM_SETTINGS_KEY, settings);
      // Раздел 16.2: начало ночного окна меняет расписание `dispatch_night_tasks`.
      void queryClient.invalidateQueries({ queryKey: PERIODIC_TASKS_KEY });
    },
  });
}

const INTEGRATIONS_KEY = ["admin", "integrations"] as const;

/** Раздел 15.5, 15.6: адрес Jira — только администратору. */
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

const BACKUP_SETTINGS_KEY = ["admin", "backup-settings"] as const;
export const BACKUP_RUNNING_POLL_MS = 10_000;

function backupRunning(settings: BackupSettings | undefined): boolean {
  return [settings?.last_backup, settings?.last_verify].some((run) => run?.status === BackupRunStatus.RUNNING);
}

/** Раздел 15.5, 20.4: настройки бэкапа в S3 и итоги последних запусков. */
export function useBackupSettings() {
  return useQuery({
    queryKey: BACKUP_SETTINGS_KEY,
    queryFn: () => api.get<BackupSettings>("/system-settings/backup"),
    // Пока бэкап или проверка идут, итог появится без перезагрузки страницы.
    refetchInterval: (query) => (backupRunning(query.state.data) ? BACKUP_RUNNING_POLL_MS : false),
  });
}

export function useUpdateBackupSettings() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: BackupSettingsUpdate) =>
      api.put<BackupSettings>("/system-settings/backup", body),
    onSuccess: (settings) => queryClient.setQueryData(BACKUP_SETTINGS_KEY, settings),
  });
}

/** Проверяются сохранённые настройки — как их возьмёт ночной бэкап. */
export function useCheckBackupConnection() {
  return useMutation({
    mutationFn: () => api.post<BackupConnectionCheck>("/system-settings/backup/check"),
  });
}

export function useLibraryUsage() {
  return useQuery({
    queryKey: ["admin", "library-usage"],
    queryFn: () => api.get<LibraryUsage[]>("/nodes/library-usage"),
  });
}

const LLM_PROXY_KEY = ["admin", "llm-proxy"] as const;

/** Раздел 15.5: состояние LLM-прокси и всех его учёток. */
export function useLlmProxyState() {
  return useQuery({ queryKey: LLM_PROXY_KEY, queryFn: () => api.get<ProxyState>("/llm-proxy") });
}

export function useRefreshProxyCredential() {
  return useInvalidatingMutation(
    (name: string) => api.post("/llm-proxy/credentials/refresh", { name }),
    [LLM_PROXY_KEY],
  );
}

export function useResetProxyCooldown() {
  return useInvalidatingMutation(
    (name: string) => api.post("/llm-proxy/credentials/cooldown/reset", { name }),
    [LLM_PROXY_KEY],
  );
}

/** Удаляется только учётка «без владельца». */
export function useDeleteProxyCredential() {
  return useInvalidatingMutation(
    (name: string) => api.delete(`/llm-proxy/credentials?name=${encodeURIComponent(name)}`),
    [LLM_PROXY_KEY],
  );
}
