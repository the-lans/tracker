import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/apiClient";
import type { McpServer, McpServerCreateRequest, McpServerUpdateRequest } from "@/lib/types";

const KEY = ["mcp-servers"] as const;

export function useMcpServers(options: { enabled?: boolean } = {}) {
  return useQuery({
    queryKey: KEY,
    queryFn: () => api.get<McpServer[]>("/mcp-servers"),
    enabled: options.enabled ?? true,
  });
}

export function useCreateMcpServer() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: McpServerCreateRequest) => api.post<McpServer>("/mcp-servers", body),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: KEY }),
  });
}

export function useUpdateMcpServer(mcpServerId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: McpServerUpdateRequest) =>
      api.patch<McpServer>(`/mcp-servers/${mcpServerId}`, body),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: KEY }),
  });
}

export function useDeleteMcpServer() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (mcpServerId: string) => api.delete(`/mcp-servers/${mcpServerId}`),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: KEY }),
  });
}
