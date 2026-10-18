import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/apiClient";
import type { EnvVariable, EnvVariableCreateRequest, EnvVariableUpdateRequest } from "@/lib/types";

const KEY = ["env-variables"] as const;

export function useEnvVariables() {
  return useQuery({ queryKey: KEY, queryFn: () => api.get<EnvVariable[]>("/env-variables") });
}

export function useCreateEnvVariable() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: EnvVariableCreateRequest) => api.post<EnvVariable>("/env-variables", body),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: KEY }),
  });
}

export function useUpdateEnvVariable(envVariableId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: EnvVariableUpdateRequest) =>
      api.patch<EnvVariable>(`/env-variables/${envVariableId}`, body),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: KEY }),
  });
}

export function useDeleteEnvVariable() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (envVariableId: string) => api.delete(`/env-variables/${envVariableId}`),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: KEY }),
  });
}

export function useRevealEnvVariable() {
  return useMutation({
    mutationFn: (envVariableId: string) =>
      api.get<{ value: string }>(`/env-variables/${envVariableId}/reveal`),
  });
}
