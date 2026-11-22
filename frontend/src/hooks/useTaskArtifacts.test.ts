import { act, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, vi } from "vitest";
import { JIRA_COPY_REFETCH_INTERVAL_MS, useJiraAttachmentCopy } from "@/hooks/useTaskArtifacts";
import { useTask } from "@/hooks/useTasks";
import { makeTask } from "@/test/factories";
import { test } from "@/test/fixtures";
import { renderHookWithClient } from "@/test/renderWithProviders";

describe("useJiraAttachmentCopy", () => {
  beforeEach(() => vi.useFakeTimers({ shouldAdvanceTime: true }));
  afterEach(() => vi.useRealTimers());

  test("когда копирование закончилось, задача перечитывается и получает отрисованное описание", async ({ api }) => {
    // Фоновая задача сохраняет HTML описания уже после создания задачи.
    let copyDone = false;
    api.respond("GET /tasks/t1", () =>
      makeTask({ id: "t1", description_html: copyDone ? "<h1>Заголовок</h1>" : null }),
    );
    api.respond("GET /tasks/t1/jira-attachments", () => ({ pending: !copyDone }));
    api.respond("GET /tasks/t1/artifacts", []);

    const { result } = renderHookWithClient(() => ({
      task: useTask("t1"),
      copy: useJiraAttachmentCopy("t1", true),
    }));
    await waitFor(() => expect(result.current.copy.data?.pending).toBe(true));
    expect(result.current.task.data?.description_html).toBeNull();

    copyDone = true;
    await act(() => vi.advanceTimersByTimeAsync(JIRA_COPY_REFETCH_INTERVAL_MS));

    await waitFor(() => expect(result.current.task.data?.description_html).toBe("<h1>Заголовок</h1>"));
  });
});
