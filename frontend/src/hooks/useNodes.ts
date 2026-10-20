import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/apiClient";
import type { NodeCreateRequest, NodeItem, NodeUpdateRequest } from "@/lib/types";

const nodeKeys = {
  all: ["nodes"] as const,
  list: (params: { libraryOnly?: boolean; includeArchived?: boolean }) =>
    ["nodes", "list", params] as const,
};

export function useNodes(params: { libraryOnly?: boolean; includeArchived?: boolean } = {}) {
  return useQuery({
    queryKey: nodeKeys.list(params),
    queryFn: () =>
      api.get<NodeItem[]>("/nodes", {
        library_only: params.libraryOnly,
        include_archived: params.includeArchived,
      }),
  });
}

export function useCreateNode() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: NodeCreateRequest) => api.post<NodeItem>("/nodes", body),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: nodeKeys.all });
      // Ноды пайплайна раздаются отдельным эндпоинтом (`usePipelineNodes`) —
      // мутация здесь должна протухнуть и его кэш тоже.
      void queryClient.invalidateQueries({ queryKey: ["pipelines"] });
    },
  });
}

export function useUpdateNode(nodeId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: NodeUpdateRequest) => api.patch<NodeItem>(`/nodes/${nodeId}`, body),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: nodeKeys.all });
      void queryClient.invalidateQueries({ queryKey: ["pipelines"] });
    },
  });
}

export function useDeleteNode() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (nodeId: string) => api.delete(`/nodes/${nodeId}`),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: nodeKeys.all });
      void queryClient.invalidateQueries({ queryKey: ["pipelines"] });
    },
  });
}
