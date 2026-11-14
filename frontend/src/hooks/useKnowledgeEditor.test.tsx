import { act, waitFor } from "@testing-library/react";
import { describe, expect } from "vitest";
import { test } from "@/test/fixtures";
import { renderHookWithClient } from "@/test/renderWithProviders";
import { useKnowledgeEditor } from "@/hooks/useKnowledgeEditor";
import type { KnowledgeEntry } from "@/lib/knowledge.types";

const first: KnowledgeEntry = {id:"a",path:"a.md",version:1,is_directory:false,deleted_at:null};
const second: KnowledgeEntry = {...first,id:"b",path:"b.md"};

describe("useKnowledgeEditor", () => {
  test("устаревший ответ не заменяет новый файл", async ({api}) => {
    let finishFirst!: (value: unknown) => void;
    api.respond("GET /knowledge/entries/a/content", () => new Promise((resolve) => { finishFirst = resolve; }));
    api.respond("GET /knowledge/entries/b/content", {content:"second",version:2});
    const {result} = renderHookWithClient(() => useKnowledgeEditor());
    let pending!: Promise<boolean>;
    act(() => { pending = result.current.open(first); });
    await waitFor(() => expect(result.current.loading).toBe(true));
    await act(async () => { await result.current.open(second); });
    await act(async () => { finishFirst({content:"stale",version:1}); await pending; });
    expect(result.current.entry?.id).toBe("b");
    expect(result.current.text).toBe("second");
    expect(result.current.loading).toBe(false);
  });

  test("ответ сохранения не меняет другой выбранный файл", async ({api}) => {
    api.respond("GET /knowledge/entries/b/content", {content:"second",version:2});
    const {result} = renderHookWithClient(() => useKnowledgeEditor());
    const generation = result.current.generation();
    await act(async () => { await result.current.open(second); });
    act(() => result.current.acceptSaved(first,"first saved",generation));
    expect(result.current.entry?.id).toBe("b");
    expect(result.current.originalText).toBe("second");
  });
});
