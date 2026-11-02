import { screen, within } from "@testing-library/react";
import { describe, expect } from "vitest";
import { LlmAccountsPage } from "@/pages/LlmAccountsPage";
import { LlmAccountStatus, type LlmAccount } from "@/lib/types";
import type { MockedApi } from "@/test/apiMock";
import { makeLlmAccount, makeLlmProvider, makeUser } from "@/test/factories";
import { test } from "@/test/fixtures";
import { renderWithProviders } from "@/test/renderWithProviders";

const claude = makeLlmAccount({ id: "a1", label: "Claude — основной", switch_order: 0 });
const codex = makeLlmAccount({
  id: "a2",
  label: "Codex — запасной",
  provider: "openai",
  default_model: "gpt-5.5-codex",
  switch_order: 1,
});

function renderPage(api: MockedApi, accounts: LlmAccount[]) {
  api.respond("GET /llm-accounts", accounts);
  api.respond("GET /llm-accounts/providers", [
    makeLlmProvider(),
    makeLlmProvider({ id: "openai", label: "Codex (OpenAI)" }),
  ]);
  api.respond("GET /profile", makeUser({ llm_switch_threshold_5h_pct: 80 }));
  return renderWithProviders(<LlmAccountsPage />);
}

describe("LlmAccountsPage", () => {
  test("показывает аккаунты в порядке переключения с провайдером и моделью", async ({ api }) => {
    renderPage(api, [claude, codex]);

    expect(await screen.findByText("Claude (Anthropic) · claude-opus-5-5 · высокий")).toBeInTheDocument();
    expect(screen.getByText("Codex (OpenAI) · gpt-5.5-codex · высокий")).toBeInTheDocument();
  });

  describe("порядок ↑/↓", () => {
    test("перестановка отправляет весь новый порядок", async ({ api }) => {
      const { user } = renderPage(api, [claude, codex]);

      await user.click(await screen.findByRole("button", { name: "Переместить ниже: Claude — основной" }));

      expect(api.mutations()).toEqual([
        { method: "PUT", path: "/llm-accounts/order", body: { account_ids: ["a2", "a1"] } },
      ]);
    });

    test.for([
      { name: "Переместить выше: Claude — основной" },
      { name: "Переместить ниже: Codex — запасной" },
    ])("$name — у края списка неактивна", async ({ name }, { api }) => {
      renderPage(api, [claude, codex]);

      expect(await screen.findByRole("button", { name })).toBeDisabled();
    });
  });

  describe("вход", () => {
    test.for([
      { signed_in: false, status: LlmAccountStatus.LOGIN_REQUIRED, button: "Войти" },
      { signed_in: true, status: LlmAccountStatus.LOGIN_REQUIRED, button: "Войти заново" },
    ])("$status, вход был: $signed_in → «$button»", async ({ signed_in, status, button }, { api }) => {
      renderPage(api, [makeLlmAccount({ signed_in, status })]);

      expect(await screen.findByRole("button", { name: button })).toBeInTheDocument();
    });

    test("у активного аккаунта кнопки входа нет", async ({ api }) => {
      renderPage(api, [claude]);

      await screen.findByText("Claude — основной");
      expect(screen.queryByRole("button", { name: /Войти/ })).not.toBeInTheDocument();
    });
  });

  test.for([
    { status: LlmAccountStatus.ACTIVE, button: "Выключить", enabled: false },
    { status: LlmAccountStatus.DISABLED, button: "Включить", enabled: true },
  ])("«$button» меняет включение аккаунта", async ({ status, button, enabled }, { api }) => {
    const { user } = renderPage(api, [makeLlmAccount({ status })]);

    await user.click(await screen.findByRole("button", { name: button }));

    expect(api.mutations()).toEqual([{ method: "PATCH", path: "/llm-accounts/acc1", body: { enabled } }]);
  });

  test("расход окна на пороге профиля и выше выделен", async ({ api }) => {
    renderPage(api, [makeLlmAccount({ usage_5h_pct: "85.00", usage_week_pct: "12.50" })]);

    const fiveHours = await screen.findByLabelText("5 часов: 85%");
    expect(within(fiveHours).getByText("85%")).toHaveClass("text-warning-text");
    expect(within(screen.getByLabelText("Неделя: 12.5%")).getByText("12.5%")).not.toHaveClass(
      "text-warning-text",
    );
  });

  test("без входа расход не показывается", async ({ api }) => {
    renderPage(api, [makeLlmAccount({ signed_in: false, status: LlmAccountStatus.LOGIN_REQUIRED })]);

    await screen.findByText("Claude Max — команда");
    expect(screen.queryByLabelText(/5 часов/)).not.toBeInTheDocument();
  });

  test("неизвестный расход — прочерк", async ({ api }) => {
    renderPage(api, [claude]);

    expect(await screen.findByLabelText("5 часов: неизвестно")).toHaveTextContent("—");
  });
});
