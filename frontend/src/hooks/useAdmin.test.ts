import { act } from "@testing-library/react";
import { describe, expect } from "vitest";
import { useUpdateSystemSettings } from "@/hooks/useAdmin";
import { test } from "@/test/fixtures";
import { createTestQueryClient, renderHookWithClient } from "@/test/renderWithProviders";

const SETTINGS = {
  default_timeout_seconds: 900,
  default_max_retries: 2,
  default_retry_base_delay_seconds: 10,
  night_window_start: "18:00:00",
  night_window_end: "19:30:00",
};

describe("useUpdateSystemSettings", () => {
  test("сохранение обновляет настройки и перечитывает расписание периодических задач", async ({ api }) => {
    api.respond("PUT /system-settings", SETTINGS);
    const queryClient = createTestQueryClient();
    queryClient.setQueryData(["admin", "periodic-tasks"], []);
    const { result } = renderHookWithClient(() => useUpdateSystemSettings(), { queryClient });

    await act(() => result.current.mutateAsync(SETTINGS));

    expect(queryClient.getQueryData(["system-settings"])).toEqual(SETTINGS);
    expect(queryClient.getQueryState(["admin", "periodic-tasks"])?.isInvalidated).toBe(true);
  });
});
