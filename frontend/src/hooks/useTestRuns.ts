import { useQuery } from "@tanstack/react-query";
import { useInvalidatingMutation } from "@/hooks/useInvalidatingMutation";
import { api } from "@/lib/apiClient";
import type { TestRun } from "@/lib/types";

export const testRunsKey = (taskId: string) => ["tasks", taskId, "test-runs"] as const;
export function useTestRuns(taskId: string) {
  return useQuery({
    queryKey: testRunsKey(taskId),
    queryFn: () => api.get<TestRun[]>(`/tasks/${taskId}/test-runs`),
    refetchInterval: 2000,
  });
}
export function useStartTestRun(taskId: string) {
  return useInvalidatingMutation(
    (body: { repository_id: string; check: string; idempotency_key: string }) =>
      api.post<TestRun>(`/tasks/${taskId}/test-runs`, body), [testRunsKey(taskId)],
  );
}
export function useTestRunAction(taskId: string) {
  return useInvalidatingMutation(
    ({ runId, action }: { runId: string; action: "stop" | "cleanup" }) =>
      api.post(`/tasks/${taskId}/test-runs/${runId}/${action}`), [testRunsKey(taskId)],
  );
}

export function useTestRun(taskId: string, runId: string, enabled: boolean) {
  return useQuery({
    queryKey: [...testRunsKey(taskId), runId],
    queryFn: () => api.get<TestRun>(`/tasks/${taskId}/test-runs/${runId}`),
    enabled,
    refetchInterval: enabled ? 2000 : false,
  });
}
