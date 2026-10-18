import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/apiClient";
import type { NodeItem, Pipeline } from "@/lib/types";

const pipelineKeys = {
  all: ["pipelines"] as const,
  list: (includeArchived: boolean) => ["pipelines", "list", includeArchived] as const,
  detail: (id: string) => ["pipelines", "detail", id] as const,
  nodes: (id: string) => ["pipelines", id, "nodes"] as const,
};

export function usePipelines(includeArchived = false) {
  return useQuery({
    queryKey: pipelineKeys.list(includeArchived),
    queryFn: () =>
      api.get<Pipeline[]>("/pipelines", { include_archived: includeArchived }),
  });
}

export function usePipeline(pipelineId: string | undefined) {
  return useQuery({
    queryKey: pipelineId ? pipelineKeys.detail(pipelineId) : ["pipelines", "detail", "none"],
    queryFn: () => api.get<Pipeline>(`/pipelines/${pipelineId}`),
    enabled: Boolean(pipelineId),
  });
}

export function usePipelineNodes(pipelineId: string | undefined) {
  return useQuery({
    queryKey: pipelineId ? pipelineKeys.nodes(pipelineId) : ["pipelines", "none", "nodes"],
    queryFn: () => api.get<NodeItem[]>(`/pipelines/${pipelineId}/nodes`),
    enabled: Boolean(pipelineId),
  });
}

export function useCreatePipeline() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (name: string) => api.post<Pipeline>("/pipelines", { name }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: pipelineKeys.all }),
  });
}

export function useUpdatePipeline(pipelineId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: { name?: string; is_archived?: boolean }) =>
      api.patch<Pipeline>(`/pipelines/${pipelineId}`, body),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: pipelineKeys.all });
      void queryClient.invalidateQueries({ queryKey: pipelineKeys.detail(pipelineId) });
    },
  });
}

export function useDeletePipeline() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (pipelineId: string) => api.delete(`/pipelines/${pipelineId}`),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: pipelineKeys.all }),
  });
}
