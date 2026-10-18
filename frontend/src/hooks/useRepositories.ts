import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/apiClient";
import type { Repository, RepositoryCreateRequest, RepositoryUpdateRequest } from "@/lib/types";

const KEY = ["repositories"] as const;

export function useRepositories() {
  return useQuery({ queryKey: KEY, queryFn: () => api.get<Repository[]>("/repositories") });
}

export function useCreateRepository() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: RepositoryCreateRequest) => api.post<Repository>("/repositories", body),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: KEY }),
  });
}

export function useUpdateRepository(repositoryId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: RepositoryUpdateRequest) =>
      api.patch<Repository>(`/repositories/${repositoryId}`, body),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: KEY }),
  });
}

export function useDeleteRepository() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (repositoryId: string) => api.delete(`/repositories/${repositoryId}`),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: KEY }),
  });
}
