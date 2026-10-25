import { useQuery } from "@tanstack/react-query";
import { useInvalidatingMutation } from "@/hooks/useInvalidatingMutation";
import { api } from "@/lib/apiClient";
import type { LlmAccount, LlmAccountCreateRequest, LlmAccountUpdateRequest } from "@/lib/types";

const KEY = ["llm-accounts"] as const;

export function useLlmAccounts() {
  return useQuery({ queryKey: KEY, queryFn: () => api.get<LlmAccount[]>("/llm-accounts") });
}

export function useCreateLlmAccount() {
  return useInvalidatingMutation(
    (body: LlmAccountCreateRequest) => api.post<LlmAccount>("/llm-accounts", body),
    [KEY],
  );
}

export function useUpdateLlmAccount(llmAccountId: string) {
  return useInvalidatingMutation(
    (body: LlmAccountUpdateRequest) => api.patch<LlmAccount>(`/llm-accounts/${llmAccountId}`, body),
    [KEY],
  );
}

export function useDeleteLlmAccount() {
  return useInvalidatingMutation(
    (llmAccountId: string) => api.delete(`/llm-accounts/${llmAccountId}`),
    [KEY],
  );
}
