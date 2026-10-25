import { useMutation, useQueryClient, type QueryKey } from "@tanstack/react-query";

/** Мутация, после успеха которой перечитываются списки с ключами `keys`. */
export function useInvalidatingMutation<TData, TVariables>(
  mutationFn: (variables: TVariables) => Promise<TData>,
  keys: readonly QueryKey[],
) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn,
    onSuccess: () =>
      void Promise.all(keys.map((queryKey) => queryClient.invalidateQueries({ queryKey }))),
  });
}
