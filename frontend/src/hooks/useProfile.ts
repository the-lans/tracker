import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/apiClient";
import type {
  JiraConnectionUpdate,
  JiraIssueDraft,
  JiraServer,
  SftpConnection,
  SshKeyUpdateRequest,
  User,
} from "@/lib/types";

const PROFILE_KEY = ["profile"] as const;

/** Раздел 15.1: собственные данные пользователя, в том числе SSH-ключ SFTP-шлюза. */
export function useProfile() {
  return useQuery({ queryKey: PROFILE_KEY, queryFn: () => api.get<User>("/profile") });
}

export function useUpdateSshKey() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: SshKeyUpdateRequest) => api.put<User>("/profile/ssh-key", body),
    onSuccess: (profile) => queryClient.setQueryData(PROFILE_KEY, profile),
  });
}

export function useDeleteSshKey() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => api.delete<User>("/profile/ssh-key"),
    onSuccess: (profile) => queryClient.setQueryData(PROFILE_KEY, profile),
  });
}

/** Раздел 15.1: хост, порт, логин и отпечаток сервера для подключения по SFTP. */
export function useSftpConnection() {
  return useQuery({
    queryKey: ["profile", "sftp"] as const,
    queryFn: () => api.get<SftpConnection>("/profile/sftp"),
  });
}

export const JIRA_SERVER_KEY = ["jira", "server"] as const;

/** Раздел 15.6: адрес Jira из «Системных настроек» — сервер выбирает администратор. */
export function useJiraServer() {
  return useQuery({
    queryKey: JIRA_SERVER_KEY,
    queryFn: () => api.get<JiraServer>("/jira/server"),
  });
}

/** Раздел 15.6: личный доступ к Jira (email и токен) для импорта задач. */
export function useUpdateJiraConnection() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: JiraConnectionUpdate) => api.put<User>("/profile/jira", body),
    onSuccess: (profile) => queryClient.setQueryData(PROFILE_KEY, profile),
  });
}

export function useDeleteJiraConnection() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => api.delete<User>("/profile/jira"),
    onSuccess: (profile) => queryClient.setQueryData(PROFILE_KEY, profile),
  });
}

/** Раздел 15.6: черновик формы новой задачи по ключу Jira — по нажатию кнопки. */
export function useJiraIssueDraft() {
  return useMutation({
    mutationFn: (key: string) =>
      api.get<JiraIssueDraft>(`/jira/issues/${encodeURIComponent(key.trim())}`),
  });
}
