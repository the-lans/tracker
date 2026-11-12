import { useMutation, useQuery } from "@tanstack/react-query";
import { useInvalidatingMutation } from "@/hooks/useInvalidatingMutation";
import { api } from "@/lib/apiClient";
import type {
  Repository,
  RepositoryCreateRequest,
  RepositoryDefaultBranchRequest,
  RepositoryDefaultBranchResponse,
  RepositoryUpdateRequest,
} from "@/lib/types";

const KEY = ["repositories"] as const;

export function useRepositories() {
  return useQuery({ queryKey: KEY, queryFn: () => api.get<Repository[]>("/repositories") });
}

export function useCreateRepository() {
  return useInvalidatingMutation(
    (body: RepositoryCreateRequest) => api.post<Repository>("/repositories", body),
    [KEY],
  );
}

export function useUpdateRepository(repositoryId: string) {
  return useInvalidatingMutation(
    (body: RepositoryUpdateRequest) => api.patch<Repository>(`/repositories/${repositoryId}`, body),
    [KEY],
  );
}

export function useDeleteRepository() {
  return useInvalidatingMutation(
    (repositoryId: string) => api.delete(`/repositories/${repositoryId}`),
    [KEY],
  );
}

/** Раздел 3.1: ветка по умолчанию с git-сервера — по адресу и доступу из формы. */
export function useRemoteDefaultBranch() {
  return useMutation({
    mutationFn: (body: RepositoryDefaultBranchRequest) =>
      api.post<RepositoryDefaultBranchResponse>("/repositories/default-branch", body),
  });
}
