import { useQuery } from "@tanstack/react-query";
import { useInvalidatingMutation } from "@/hooks/useInvalidatingMutation";
import { api } from "@/lib/apiClient";
import type {
  GitCredential, GitCredentialCheck, GitCredentialInput,
} from "@/components/admin/gitCredentials.types";

export type { GitCredential, GitCredentialInput } from "@/components/admin/gitCredentials.types";
const KEY = ["git-credentials"] as const;
export function useGitCredentials() {
  return useQuery({ queryKey: KEY, queryFn: () => api.get<GitCredential[]>("/git-credentials") });
}
export function useSaveGitCredential(id?: string) {
  return useInvalidatingMutation(
    (body: GitCredentialInput) => id
      ? api.put<GitCredential>(`/git-credentials/${id}`, body)
      : api.post<GitCredential>("/git-credentials", body),
    [KEY],
  );
}
export function useDeleteGitCredential() {
  return useInvalidatingMutation((id: string) => api.delete(`/git-credentials/${id}`), [KEY]);
}
/** Проверка чтения; ключ хоста, запомненный ею (раздел 19.3), появляется в списке. */
export function useCheckGitCredential(id?: string) {
  return useInvalidatingMutation(
    (gitUrl: string) => api.post<GitCredentialCheck>(`/git-credentials/${id}/check`, { git_url: gitUrl }),
    [KEY],
  );
}
