import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/apiClient";
import type { LlmAccount, LlmAccountCreateRequest, LlmAccountUpdateRequest } from "@/lib/types";

const KEY = ["llm-accounts"] as const;

export function useLlmAccounts() {
  return useQuery({ queryKey: KEY, queryFn: () => api.get<LlmAccount[]>("/llm-accounts") });
}

export function useCreateLlmAccount() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: LlmAccountCreateRequest) => api.post<LlmAccount>("/llm-accounts", body),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: KEY }),
  });
}

export function useUpdateLlmAccount(llmAccountId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: LlmAccountUpdateRequest) =>
      api.patch<LlmAccount>(`/llm-accounts/${llmAccountId}`, body),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: KEY }),
  });
}

export function useDeleteLlmAccount() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (llmAccountId: string) => api.delete(`/llm-accounts/${llmAccountId}`),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: KEY }),
  });
}
