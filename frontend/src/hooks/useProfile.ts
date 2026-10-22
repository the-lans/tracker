import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/apiClient";
import type { SftpConnection, SshKeyUpdateRequest, User } from "@/lib/types";

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
