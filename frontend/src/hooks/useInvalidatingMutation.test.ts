import { act } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { useInvalidatingMutation } from "@/hooks/useInvalidatingMutation";
import { createTestQueryClient, renderHookWithClient } from "@/test/renderWithProviders";

const KEYS = [["repositories"], ["templates", "list"]] as const;
const UNTOUCHED = ["llm-accounts"];

function renderMutation(mutationFn: () => Promise<unknown>) {
  const queryClient = createTestQueryClient();
  for (const key of [...KEYS, UNTOUCHED]) queryClient.setQueryData(key, []);
  queryClient.setQueryData(["templates", "list", "archived"], []);
  return renderHookWithClient(() => useInvalidatingMutation(mutationFn, KEYS), { queryClient });
}

const invalidated = (queryClient: ReturnType<typeof createTestQueryClient>, key: readonly unknown[]) =>
  queryClient.getQueryState(key)?.isInvalidated;

describe("useInvalidatingMutation", () => {
  it("после успеха перечитываются переданные списки и их вложенные ключи", async () => {
    const { result, queryClient } = renderMutation(async () => ({ id: "r1" }));

    await act(() => result.current.mutateAsync(undefined));

    for (const key of KEYS) expect(invalidated(queryClient, key)).toBe(true);
    expect(invalidated(queryClient, ["templates", "list", "archived"])).toBe(true);
    expect(invalidated(queryClient, UNTOUCHED)).toBe(false);
  });

  it("после ошибки списки не трогаются, ошибка доходит до вызывающего", async () => {
    const failure = new Error("409");
    const { result, queryClient } = renderMutation(vi.fn().mockRejectedValue(failure));

    await act(() => expect(result.current.mutateAsync(undefined)).rejects.toBe(failure));

    for (const key of KEYS) expect(invalidated(queryClient, key)).toBe(false);
  });
});
