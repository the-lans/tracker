import { useQuery } from "@tanstack/react-query";
import { useInvalidatingMutation } from "@/hooks/useInvalidatingMutation";
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
  return useInvalidatingMutation(
    (body: McpServerCreateRequest) => api.post<McpServer>("/mcp-servers", body),
    [KEY],
  );
}

export function useUpdateMcpServer(mcpServerId: string) {
  return useInvalidatingMutation(
    (body: McpServerUpdateRequest) => api.patch<McpServer>(`/mcp-servers/${mcpServerId}`, body),
    [KEY],
  );
}

export function useDeleteMcpServer() {
  return useInvalidatingMutation(
    (mcpServerId: string) => api.delete(`/mcp-servers/${mcpServerId}`),
    [KEY],
  );
}
