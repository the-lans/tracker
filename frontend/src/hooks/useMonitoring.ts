import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/apiClient";
import type {
  DiskUsage,
  LlmUsage,
  NodeStats,
  ServerOverview,
  StatsPeriod,
  TaskContainer,
} from "@/lib/monitoring.types";

/**
 * Раздел 15.5: блоки страницы «Мониторинг» — каждый своим запросом, чтобы
 * медленный блок (опрос воркеров, docker) не задерживал остальные.
 */
const MONITORING_KEY = ["admin", "monitoring"] as const;
const LIVE_REFRESH_MS = 15_000;
const SLOW_REFRESH_MS = 60_000;

export function useServerOverview() {
  return useQuery({
    queryKey: [...MONITORING_KEY, "overview"],
    queryFn: () => api.get<ServerOverview>("/monitoring/overview"),
    refetchInterval: LIVE_REFRESH_MS,
  });
}

export function useNodeStats(period: StatsPeriod) {
  return useQuery({
    queryKey: [...MONITORING_KEY, "node-stats", period],
    queryFn: () => api.get<NodeStats>("/monitoring/node-stats", { period }),
    refetchInterval: SLOW_REFRESH_MS,
  });
}

export function useLlmUsage() {
  return useQuery({
    queryKey: [...MONITORING_KEY, "llm-usage"],
    queryFn: () => api.get<LlmUsage>("/monitoring/llm-usage"),
    refetchInterval: SLOW_REFRESH_MS,
  });
}

export function useDiskUsage() {
  return useQuery({
    queryKey: [...MONITORING_KEY, "disk"],
    queryFn: () => api.get<DiskUsage>("/monitoring/disk"),
    refetchInterval: SLOW_REFRESH_MS,
  });
}

export function useTaskContainers() {
  return useQuery({
    queryKey: [...MONITORING_KEY, "containers"],
    queryFn: () => api.get<TaskContainer[]>("/monitoring/containers"),
    refetchInterval: LIVE_REFRESH_MS,
  });
}
