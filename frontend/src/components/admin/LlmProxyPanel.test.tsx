import { screen, within } from "@testing-library/react";
import { describe, expect } from "vitest";
import { LlmProxyPanel } from "@/components/admin/LlmProxyPanel";
import { LlmAccountStatus, type ProxyCredential, type ProxyState } from "@/lib/types";
import type { MockedApi } from "@/test/apiMock";
import { test } from "@/test/fixtures";
import { renderWithProviders } from "@/test/renderWithProviders";

function makeCredential(overrides: Partial<ProxyCredential> = {}): ProxyCredential {
  return {
    name: "claude-anna@example.com.json",
    provider: "claude",
    disabled: false,
    requires_sign_in: false,
    quota_blocked: false,
    status: "active",
    account_id: "a1",
    account_label: "Claude — основной",
    account_status: LlmAccountStatus.ACTIVE,
    owner_email: "anna@example.com",
    usage_5h_pct: "42.00",
    usage_week_pct: null,
    ...overrides,
  };
}

const ORPHAN = makeCredential({
  name: "codex-old@example.com.json",
  provider: "codex",
  account_id: null,
  account_label: null,
  account_status: null,
  owner_email: null,
  usage_5h_pct: null,
});

function renderPanel(api: MockedApi, state: Partial<ProxyState> = {}) {
  api.respond("GET /llm-proxy", {
    available: true,
    error: null,
    version: "v8.0.48",
    latest_version: "v8.0.48",
    credentials: [makeCredential()],
    ...state,
  });
  return renderWithProviders(<LlmProxyPanel />);
}

const rowOf = async (text: string) => (await screen.findByText(text)).closest<HTMLElement>(".flex-col")!;

describe("LlmProxyPanel", () => {
  test("состояние и версии прокси", async ({ api }) => {
    renderPanel(api, { latest_version: "v8.1.0" });

    expect(await screen.findByText("Прокси доступен")).toBeInTheDocument();
    expect(screen.getByText("Версия v8.0.48, последняя выпущенная — v8.1.0")).toBeInTheDocument();
    expect(screen.getByText(/install\.sh --update/)).toBeInTheDocument();
  });

  test("недоступный прокси — с причиной", async ({ api }) => {
    renderPanel(api, { available: false, error: "Сервис не отвечает", credentials: [] });

    expect(await screen.findByText("Прокси недоступен")).toBeInTheDocument();
    expect(screen.getByText("Сервис не отвечает")).toBeInTheDocument();
  });

  test("учётка с владельцем — без удаления, с расходом", async ({ api }) => {
    renderPanel(api);

    const row = await rowOf("Claude — основной");
    expect(row).toHaveTextContent("claude · anna@example.com · 5 ч 42%");
    expect(within(row).queryByRole("button", { name: /Удалить/ })).not.toBeInTheDocument();
  });

  test("учётку без владельца можно удалить", async ({ api }) => {
    const { user } = renderPanel(api, { credentials: [ORPHAN] });

    await user.click(await screen.findByRole("button", { name: `Удалить ${ORPHAN.name}` }));
    await user.click(screen.getByRole("button", { name: "Удалить" }));

    expect(api.mutations()).toEqual([
      { method: "DELETE", path: "/llm-proxy/credentials", body: undefined },
    ]);
  });

  test.for([
    { button: "Обновить токен", path: "/llm-proxy/credentials/refresh", blocked: false },
    { button: "Снять паузу", path: "/llm-proxy/credentials/cooldown/reset", blocked: true },
  ])("«$button» — по имени учётки", async ({ button, path, blocked }, { api }) => {
    const { user } = renderPanel(api, { credentials: [makeCredential({ quota_blocked: blocked })] });

    await user.click(await screen.findByRole("button", { name: button }));

    expect(api.mutations()).toEqual([
      { method: "POST", path, body: { name: "claude-anna@example.com.json" } },
    ]);
  });

  test("без паузы кнопки «Снять паузу» нет", async ({ api }) => {
    renderPanel(api);

    await screen.findByText("Claude — основной");
    expect(screen.queryByRole("button", { name: "Снять паузу" })).not.toBeInTheDocument();
  });
});
