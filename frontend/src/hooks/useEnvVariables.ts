import { useMutation, useQuery } from "@tanstack/react-query";
import { useInvalidatingMutation } from "@/hooks/useInvalidatingMutation";
import { api } from "@/lib/apiClient";
import type { EnvVariable, EnvVariableCreateRequest, EnvVariableUpdateRequest } from "@/lib/types";

const KEY = ["env-variables"] as const;

export function useEnvVariables() {
  return useQuery({ queryKey: KEY, queryFn: () => api.get<EnvVariable[]>("/env-variables") });
}

export function useCreateEnvVariable() {
  return useInvalidatingMutation(
    (body: EnvVariableCreateRequest) => api.post<EnvVariable>("/env-variables", body),
    [KEY],
  );
}

export function useUpdateEnvVariable(envVariableId: string) {
  return useInvalidatingMutation(
    (body: EnvVariableUpdateRequest) =>
      api.patch<EnvVariable>(`/env-variables/${envVariableId}`, body),
    [KEY],
  );
}

export function useDeleteEnvVariable() {
  return useInvalidatingMutation(
    (envVariableId: string) => api.delete(`/env-variables/${envVariableId}`),
    [KEY],
  );
}

export function useRevealEnvVariable() {
  return useMutation({
    mutationFn: (envVariableId: string) =>
      api.get<{ value: string }>(`/env-variables/${envVariableId}/reveal`),
  });
}
