import { useCallback } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useInvalidatingMutation } from "@/hooks/useInvalidatingMutation";
import { api } from "@/lib/apiClient";
import { hasUsableAccount } from "@/lib/llmAccounts";
import type {
  LlmAccount,
  LlmAccountCreateRequest,
  LlmAccountUpdateRequest,
  LlmLoginStart,
  LlmLoginStatus,
  LlmProvider,
} from "@/lib/types";

const KEY = ["llm-accounts"] as const;
const PROVIDERS_KEY = ["llm-providers"] as const;
// Раздел 19.7: незавершённый вход ждёт браузер пользователя — опрос статуса раз в 2 с.
const LOGIN_POLL_MS = 2000;

/** Аккаунты пользователя в порядке переключения (`switch_order`, раздел 19.7). */
export function useLlmAccounts() {
  return useQuery({ queryKey: KEY, queryFn: () => api.get<LlmAccount[]>("/llm-accounts") });
}

/**
 * Раздел 3.1, 19.7: у автора задачи есть рабочий LLM-аккаунт — промт выполнит
 * автоматически выбранный аккаунт. Пока список не загружен, ввод не
 * блокируется: запрос всё равно проверит сервер.
 */
export function useLlmAvailable(ownerId: string): boolean {
  const { data: accounts } = useLlmAccounts();
  return accounts === undefined || hasUsableAccount(accounts, ownerId);
}

/** Реестр провайдеров трекера — меняется только с релизом. */
export function useLlmProviders() {
  return useQuery({
    queryKey: PROVIDERS_KEY,
    queryFn: () => api.get<LlmProvider[]>("/llm-accounts/providers"),
    staleTime: Infinity,
  });
}

/** Модели учётки аккаунта в прокси — только после входа. */
export function useLlmAccountModels(llmAccountId: string, enabled: boolean) {
  return useQuery({
    queryKey: [...KEY, llmAccountId, "models"],
    queryFn: () => api.get<string[]>(`/llm-accounts/${llmAccountId}/models`),
    enabled,
  });
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

/** Раздел 19.7: новый порядок переключения — все аккаунты пользователя. */
export function useReorderLlmAccounts() {
  return useInvalidatingMutation(
    (accountIds: string[]) =>
      api.put<LlmAccount[]>("/llm-accounts/order", { account_ids: accountIds }),
    [KEY],
  );
}

export function useStartLlmLogin(llmAccountId: string) {
  return useMutation({
    mutationFn: () => api.post<LlmLoginStart>(`/llm-accounts/${llmAccountId}/login`),
  });
}

export function useSubmitLlmLogin(llmAccountId: string) {
  return useInvalidatingMutation(
    (redirectUrl: string) =>
      api.post<LlmLoginStatus>(`/llm-accounts/${llmAccountId}/login/callback`, {
        redirect_url: redirectUrl,
      }),
    [KEY],
  );
}

export function useCancelLlmLogin(llmAccountId: string) {
  return useInvalidatingMutation(
    () => api.delete(`/llm-accounts/${llmAccountId}/login`),
    [KEY],
  );
}

/** Перечитать аккаунты: вход, завершённый опросом статуса, меняет статус аккаунта. */
export function useRefreshLlmAccounts() {
  const queryClient = useQueryClient();
  return useCallback(() => void queryClient.invalidateQueries({ queryKey: KEY }), [queryClient]);
}

/** Статус входа, пока прокси ждёт завершения OAuth (`wait`). */
export function useLlmLoginStatus(llmAccountId: string, enabled: boolean) {
  return useQuery({
    queryKey: [...KEY, llmAccountId, "login"],
    queryFn: () => api.get<LlmLoginStatus>(`/llm-accounts/${llmAccountId}/login/status`),
    enabled,
    refetchInterval: (query) => (query.state.data?.state === "wait" ? LOGIN_POLL_MS : false),
  });
}
