import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/apiClient";
import type {
  AllowedEmail,
  AppLog,
  AppLogLevel,
  PeriodicTask,
  PeriodicTaskUpdateRequest,
  User,
  UserUpdateRequest,
} from "@/lib/types";

const USERS_KEY = ["admin", "users"] as const;
const ALLOWED_EMAILS_KEY = ["admin", "allowed-emails"] as const;
const PERIODIC_TASKS_KEY = ["admin", "periodic-tasks"] as const;

export function useUsers() {
  return useQuery({ queryKey: USERS_KEY, queryFn: () => api.get<User[]>("/users") });
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

export function useAppLogs(filters: { level?: AppLogLevel; source?: string; taskId?: string }) {
  return useQuery({
    queryKey: ["admin", "app-logs", filters],
    queryFn: () =>
      api.get<AppLog[]>("/app-logs", {
        level: filters.level,
        source: filters.source,
        task_id: filters.taskId,
      }),
    refetchInterval: 15_000,
  });
}
