import { screen, within } from "@testing-library/react";
import { describe, expect } from "vitest";
import { MonitoringPage } from "@/pages/MonitoringPage";
import {
  ContainerKind,
  ServerDependency,
  StatsPeriod,
  VolumeName,
  type DiskUsage,
  type NodeStats,
  type ServerOverview,
} from "@/lib/monitoring.types";
import { LlmAccountStatus, UserRole } from "@/lib/types";
import type { MockedApi } from "@/test/apiMock";
import { makeBackupRun, makeCurrentUser } from "@/test/factories";
import { test } from "@/test/fixtures";
import { renderWithProviders } from "@/test/renderWithProviders";

const overview: ServerOverview = {
  dependencies: [
    { name: ServerDependency.POSTGRES, ok: true, error: null },
    { name: ServerDependency.REDIS, ok: true, error: null },
    { name: ServerDependency.LLM_PROXY, ok: false, error: "LLM-прокси недоступен" },
  ],
  queues: [
    { name: "celery", workers: 2, pending: 0 },
    { name: "sessions", workers: 0, pending: 3 },
  ],
  manual_requests_queued: 4,
  manual_requests_processing: 1,
  version: "0123456789abcdef",
  deployed_at: "2026-11-12T07:00:00Z",
  maintenance: true,
  last_backup: makeBackupRun(),
  last_verify: null,
};

const stats: NodeStats = {
  period: StatsPeriod.DAY,
  since: "2026-11-11T07:00:00Z",
  total: 12,
  success: 9,
  failed: 2,
  stopped: 1,
  retries: 3,
  avg_duration_seconds: 200,
  max_duration_seconds: 3900,
  top_failing: [{ node_id: "n1", node_name: "Сборка", failed: 2 }],
};

const disk: DiskUsage = {
  volumes: [{ name: VolumeName.TASK_REPOS, size_bytes: 3 * 1024 * 1024 }],
  measured_at: null,
  database_bytes: 1024,
  free_bytes: 1024,
  total_bytes: 100 * 1024,
};

function renderPage(api: MockedApi) {
  api.respond("GET /monitoring/overview", overview);
  api.respond("GET /monitoring/node-stats", stats);
  api.respond("GET /monitoring/disk", disk);
  api.respond("GET /monitoring/llm-usage", {
    switches_24h: 5,
    accounts: [
      {
        id: "a1",
        label: "Claude — основной",
        provider: "anthropic",
        owner_email: "anna@example.com",
        status: LlmAccountStatus.ACTIVE,
        usage_5h_pct: "42.50",
        usage_week_pct: "10.00",
        usage_5h_resets_at: null,
        usage_week_resets_at: null,
        usage_checked_at: null,
        switches_to_24h: 2,
      },
    ],
  });
  api.respond("GET /monitoring/containers", [
    {
      name: "tracker-session-1",
      kind: ContainerKind.SESSION,
      task_id: "t1",
      task_code: "RR-1",
      started_at: null,
      orphaned: true,
    },
    {
      name: "tracker-node-2",
      kind: ContainerKind.NODE,
      task_id: null,
      task_code: "RR-2",
      started_at: null,
      orphaned: false,
    },
  ]);
  return renderWithProviders(<MonitoringPage />, {
    currentUser: makeCurrentUser({ role: UserRole.ADMIN }),
  });
}

function card(title: string): HTMLElement {
  return screen.getByRole("heading", { name: title }).closest("div.rounded-lg") as HTMLElement;
}

describe("MonitoringPage", () => {
  test("сводка сервера: недоступная зависимость, версия, обслуживание", async ({ api }) => {
    renderPage(api);

    await screen.findByText("LLM-прокси недоступен");
    const server = card("Состояние сервера");
    expect(within(server).getByText("LLM-прокси недоступен")).toBeInTheDocument();
    expect(within(server).getAllByText("работает")).toHaveLength(2);
    expect(within(server).getByText("недоступен")).toBeInTheDocument();
    expect(within(server).getByText("0123456")).toBeInTheDocument();
    expect(within(server).getByText("идёт обновление")).toBeInTheDocument();
  });

  test("очереди: без воркеров — красным, ручные запросы", async ({ api }) => {
    renderPage(api);

    await screen.findByText("нет воркеров");
    const queues = card("Очереди");
    expect(within(queues).getByText("2 воркера")).toBeInTheDocument();
    expect(within(queues).getByText("нет воркеров")).toBeInTheDocument();
    expect(within(queues).getByText("в очереди: 3")).toBeInTheDocument();
    expect(queues).toHaveTextContent("Ручные запросы к сессиям: 4 ждут, 1 выполняются");
  });

  test("статистика нод: показатели, длительность, топ и смена периода", async ({ api }) => {
    const { user } = renderPage(api);

    await screen.findByText("Сборка");
    const node = card("Статистика нод");
    expect(within(node).getByText("3 мин 20 с / 1 ч 5 мин")).toBeInTheDocument();
    expect(within(node).getByText("12")).toBeInTheDocument();

    await user.click(within(node).getByRole("tab", { name: "7 дней" }));

    await expect
      .poll(() => api.queriesOf("GET /monitoring/node-stats").map((query) => query.period))
      .toEqual(["day", "week"]);
  });

  test("расход LLM, диск без замера и осиротевшие контейнеры", async ({ api }) => {
    renderPage(api);

    expect(await screen.findByText("Claude — основной")).toBeInTheDocument();
    expect(screen.getByText("Переключений за сутки:")).toHaveTextContent("5");
    expect(await screen.findByText(/ещё не замерены/)).toBeInTheDocument();
    expect(within(card("Место на диске")).getByText("3 МБ")).toBeInTheDocument();
    expect(await screen.findByText("осиротевших: 1")).toBeInTheDocument();
    expect(screen.getByText("осиротел")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "RR-1" })).toHaveAttribute("href", "/tasks/t1");
  });

  test.for([
    { tab: "Активные Celery-задачи", text: "Воркеры сейчас ничего не выполняют" },
    { tab: "Выполнение нод", text: "Выполнение нод" },
  ])("вкладка «$tab»", async ({ tab, text }, { api }) => {
    const { user } = renderPage(api);

    await user.click(screen.getByRole("tab", { name: tab }));

    expect(await screen.findAllByText(text)).not.toHaveLength(0);
  });
});
