import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/apiClient";
import type { SshKeyUpdateRequest, User } from "@/lib/types";

const PROFILE_KEY = ["profile"] as const;

/** Раздел 15.1: собственные данные пользователя, в том числе SSH-ключ sshfs. */
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
