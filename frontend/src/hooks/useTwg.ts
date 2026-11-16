import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/apiClient";
import type { TwgConnection, TwgConnectionUpdate } from "@/lib/twg.types";

const KEY = ["profile", "twg"] as const;

export function useTwg() {
  return useQuery({ queryKey: KEY, queryFn: () => api.get<TwgConnection>("/profile/twg") });
}

export function useUpdateTwg() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: TwgConnectionUpdate) => api.put<TwgConnection>("/profile/twg", body),
    onSuccess: (data) => client.setQueryData(KEY, data),
  });
}

export function useDeleteTwg() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => api.delete<TwgConnection>("/profile/twg"),
    onSuccess: (data) => client.setQueryData(KEY, data),
  });
}
