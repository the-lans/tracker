import { act, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, vi } from "vitest";
import {
  BACKUP_RUNNING_POLL_MS,
  useBackupSettings,
  useUpdateSystemSettings,
} from "@/hooks/useAdmin";
import { BackupRunStatus } from "@/lib/types";
import { makeBackupRun, makeBackupSettings, makeSystemSettings } from "@/test/factories";
import { test } from "@/test/fixtures";
import { createTestQueryClient, renderHookWithClient } from "@/test/renderWithProviders";

const SETTINGS = makeSystemSettings({ night_window_start: "18:00:00", night_window_end: "19:30:00" });

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

describe("useBackupSettings", () => {
  beforeEach(() => vi.useFakeTimers({ shouldAdvanceTime: true }));
  afterEach(() => vi.useRealTimers());

  test.for([
    { run: "last_backup", status: BackupRunStatus.RUNNING, reads: 2 },
    { run: "last_verify", status: BackupRunStatus.RUNNING, reads: 2 },
    { run: "last_backup", status: BackupRunStatus.SUCCESS, reads: 1 },
    { run: "last_verify", status: BackupRunStatus.FAILED, reads: 1 },
  ] as const)("$run=$status → перечитываний: $reads", async ({ run, status, reads }, { api }) => {
    const settings = makeBackupSettings({ [run]: makeBackupRun({ status }) });
    // После первого чтения запуск завершён — опрос должен остановиться.
    const responses = [settings, makeBackupSettings({ [run]: makeBackupRun() })];
    api.respond("GET /system-settings/backup", () => responses.shift() ?? responses[0]);
    const { result } = renderHookWithClient(() => useBackupSettings());
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    await act(() => vi.advanceTimersByTimeAsync(BACKUP_RUNNING_POLL_MS * 3));

    expect(api.requests.filter((request) => request.path === "/system-settings/backup")).toHaveLength(reads);
  });
});
